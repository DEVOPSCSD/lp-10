"""
Automated unit and end-to-end tests for the Failure Detection and Recovery Lifecycle (Issue #10).
Verifies:
1. Baseline health and telemetry reporting (UP, app_health_status 1).
2. Failure simulation and detection (DOWN, HTTP 503, app_health_status 0).
3. Automated recovery execution via scripts/recover.py.
4. Post-recovery verification of application health and data integrity.
5. Execution of scripts/test_dr_lifecycle.py automation runner.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from werkzeug.serving import make_server

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as flask_app
from scripts.test_dr_lifecycle import (
    check_health,
    check_metrics,
    trigger_simulate_failure,
    run_dr_lifecycle
)


class EphemeralServerThread(threading.Thread):
    """Runs the Flask application in a background daemon thread on an ephemeral port."""

    def __init__(self, wsgi_app):
        super().__init__()
        self.server = make_server("127.0.0.1", 0, wsgi_app)
        self.port = self.server.port
        self.url = f"http://127.0.0.1:{self.port}"
        self.daemon = True

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


class TestFlaskClientFailureRecovery(unittest.TestCase):
    """Unit tests for failure injection and recovery using Flask test client."""

    def setUp(self):
        flask_app.app.config["TESTING"] = True
        self.client = flask_app.app.test_client()
        flask_app.is_healthy = True

    def tearDown(self):
        flask_app.is_healthy = True

    def test_baseline_health_and_metrics(self):
        """Verifies initial healthy state reports 200 UP and app_health_status 1."""
        resp_health = self.client.get("/health")
        self.assertEqual(resp_health.status_code, 200)
        data = resp_health.get_json()
        self.assertEqual(data.get("status"), "UP")

        resp_metrics = self.client.get("/metrics")
        self.assertEqual(resp_metrics.status_code, 200)
        self.assertIn("app_health_status 1", resp_metrics.data.decode("utf-8"))

    def test_failure_simulation_and_detection(self):
        """Verifies /simulate-failure shifts health status to 503 DOWN and metrics to 0."""
        resp_fail = self.client.post("/simulate-failure")
        self.assertEqual(resp_fail.status_code, 200)

        # Health endpoint should now report 503 DOWN
        resp_health = self.client.get("/health")
        self.assertEqual(resp_health.status_code, 503)
        data = resp_health.get_json()
        self.assertEqual(data.get("status"), "DOWN")

        # Metrics endpoint should report app_health_status 0
        resp_metrics = self.client.get("/metrics")
        self.assertIn("app_health_status 0", resp_metrics.data.decode("utf-8"))

    def test_simulate_recover_restores_health(self):
        """Verifies /simulate-recover restores health status to 200 UP and metrics to 1."""
        self.client.post("/simulate-failure")
        self.assertEqual(self.client.get("/health").status_code, 503)

        resp_recover = self.client.post("/simulate-recover")
        self.assertEqual(resp_recover.status_code, 200)

        resp_health = self.client.get("/health")
        self.assertEqual(resp_health.status_code, 200)
        self.assertEqual(resp_health.get_json().get("status"), "UP")

        resp_metrics = self.client.get("/metrics")
        self.assertIn("app_health_status 1", resp_metrics.data.decode("utf-8"))


class TestLiveServerFailureRecoveryLifecycle(unittest.TestCase):
    """End-to-end integration tests using an ephemeral live HTTP server."""

    @classmethod
    def setUpClass(cls):
        flask_app.app.config["TESTING"] = True
        cls.server_thread = EphemeralServerThread(flask_app.app)
        cls.server_thread.start()
        cls.app_url = cls.server_thread.url
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server_thread.shutdown()
        cls.server_thread.join(timeout=2)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.target_data_file = os.path.join(self.test_dir, "data", "orders.json")
        self.backups_dir = os.path.join(self.test_dir, "data", "backups")
        os.makedirs(self.backups_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.target_data_file), exist_ok=True)

        flask_app.is_healthy = True

    def tearDown(self):
        flask_app.is_healthy = True
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_live_server_probe_helpers(self):
        """Tests check_health and check_metrics against live ephemeral server."""
        is_up, code, data = check_health(self.app_url)
        self.assertTrue(is_up)
        self.assertEqual(code, 200)
        self.assertEqual(data.get("status"), "UP")

        metrics_val = check_metrics(self.app_url)
        self.assertEqual(metrics_val, 1)

    def test_live_server_failure_detection(self):
        """Tests live failure injection and failure probe detection."""
        ok = trigger_simulate_failure(self.app_url)
        self.assertTrue(ok)

        is_up, code, data = check_health(self.app_url)
        self.assertFalse(is_up)
        self.assertEqual(code, 503)
        self.assertEqual(data.get("status"), "DOWN")

        metrics_val = check_metrics(self.app_url)
        self.assertEqual(metrics_val, 0)

    def test_complete_dr_lifecycle_run(self):
        """Tests the full run_dr_lifecycle end-to-end orchestration."""
        # Seed initial orders data
        initial_orders = [
            {"name": "Lifecycle Test User", "mobile": "9990001111", "food": "Pizza", "quantity": "2", "date": "2026-10-02"}
        ]
        with open(self.target_data_file, "w", encoding="utf-8") as f:
            json.dump(initial_orders, f, indent=4)

        report = run_dr_lifecycle(
            base_url=self.app_url,
            data_file=self.target_data_file,
            backup_dirs=[self.backups_dir],
            auto_create_backup=True
        )

        self.assertTrue(report["baseline_healthy"])
        self.assertTrue(report["failure_simulated"])
        self.assertTrue(report["failure_detected"])
        self.assertTrue(report["recovery_triggered"])
        self.assertTrue(report["restoration_verified"])
        self.assertTrue(report["overall_success"])

        # Check file data restored
        self.assertTrue(os.path.exists(self.target_data_file))
        with open(self.target_data_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored, initial_orders)

    def test_cli_lifecycle_runner(self):
        """Tests running scripts/test_dr_lifecycle.py via CLI subprocess."""
        script_path = os.path.join(REPO_ROOT, "scripts", "test_dr_lifecycle.py")

        initial_orders = [{"name": "CLI Runner", "food": "Burger"}]
        with open(self.target_data_file, "w", encoding="utf-8") as f:
            json.dump(initial_orders, f, indent=4)

        proc = subprocess.run(
            [
                sys.executable,
                script_path,
                "--url", self.app_url,
                "--target", self.target_data_file,
                "--backup-dirs", self.backups_dir
            ],
            capture_output=True,
            text=True
        )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("DISASTER RECOVERY LIFECYCLE SUMMARY REPORT", proc.stdout)
        self.assertIn("overall_success          : PASS", proc.stdout)
        self.assertTrue(flask_app.is_healthy)


if __name__ == "__main__":
    unittest.main()
