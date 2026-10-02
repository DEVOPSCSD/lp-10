"""
Final End-to-End Acceptance Test Suite (Issue #12).
Verifies:
1. Application initial healthy state and Prometheus monitoring telemetry.
2. Failure injection and outage detection (Acceptance Criterion 1: Failure is detected).
3. Disaster recovery execution and database reconstruction (Acceptance Criterion 2: Recovery completes successfully).
4. Full operational restoration including ordering capability (Acceptance Criterion 3: Application is restored).
5. Comprehensive end-to-end execution and report generation via scripts/run_final_test.py.
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
import urllib.parse
import urllib.request
from werkzeug.serving import make_server

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as flask_app
from scripts.backup import backup
from scripts.recover import recover
from scripts.run_final_test import (
    query_health,
    query_metrics,
    inject_failure,
    execute_final_test_suite
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


class TestFinalDisasterRecoveryE2E(unittest.TestCase):
    """Final acceptance test suite verifying all criteria for Issue #12."""

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

        flask_app.ORDERS_FILE = self.target_data_file
        flask_app.is_healthy = True

    def tearDown(self):
        flask_app.is_healthy = True
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_criterion_1_baseline_and_telemetry(self):
        """Validates that application starts and monitoring telemetry accurately reflects state."""
        # 1. Probe /health
        is_up, code, data = query_health(self.app_url)
        self.assertTrue(is_up)
        self.assertEqual(code, 200)
        self.assertEqual(data.get("status"), "UP")

        # 2. Probe /metrics
        health_metric, uptime_metric = query_metrics(self.app_url)
        self.assertEqual(health_metric, 1)
        self.assertIsNotNone(uptime_metric)
        self.assertGreaterEqual(uptime_metric, 0.0)

    def test_criterion_2_failure_simulation_and_detection(self):
        """Acceptance Criterion 1: Verifies that failure is detected when injected."""
        # 1. Inject failure
        fail_ok = inject_failure(self.app_url)
        self.assertTrue(fail_ok)

        # 2. Verify /health returns HTTP 503 DOWN
        is_up, code, data = query_health(self.app_url)
        self.assertFalse(is_up)
        self.assertEqual(code, 503)
        self.assertEqual(data.get("status"), "DOWN")

        # 3. Verify /metrics reports app_health_status 0
        health_metric, _ = query_metrics(self.app_url)
        self.assertEqual(health_metric, 0)

    def test_criterion_3_recovery_execution(self):
        """Acceptance Criterion 2: Verifies that recovery completes successfully."""
        # Seed known order and create snapshot
        initial_data = [{"name": "Final Test User", "food": "Pasta", "quantity": "1", "date": "2026-10-02"}]
        with open(self.target_data_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        backup_file = backup(data_file=self.target_data_file, backup_dir=self.backups_dir)
        self.assertTrue(os.path.exists(backup_file))

        # Wipe data & simulate failure
        os.remove(self.target_data_file)
        inject_failure(self.app_url)

        # Execute recovery
        rec_res = recover(
            target_path=self.target_data_file,
            backup_dirs=[self.backups_dir],
            app_url=self.app_url,
            restore_health=True
        )

        self.assertTrue(rec_res["success"])
        self.assertTrue(rec_res["data_restored"])
        self.assertTrue(rec_res["app_recovered"])
        self.assertTrue(os.path.exists(self.target_data_file))

        with open(self.target_data_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored, initial_data)

    def test_criterion_4_application_restored_and_operational(self):
        """Acceptance Criterion 3: Verifies application is restored and operational post-recovery."""
        # 1. Ensure state recovered
        is_up, code, data = query_health(self.app_url)
        self.assertTrue(is_up)
        self.assertEqual(code, 200)
        self.assertEqual(data.get("status"), "UP")

        health_metric, _ = query_metrics(self.app_url)
        self.assertEqual(health_metric, 1)

        # 2. Place new order to prove ongoing read/write transactional capability
        payload = urllib.parse.urlencode({
            "name": "Post Recovery Client",
            "mobile": "5551234567",
            "food": "Lasagna",
            "quantity": "2"
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.app_url}/order",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

        # Verify new order appended to data file
        with open(self.target_data_file, "r", encoding="utf-8") as f:
            records = json.load(f)
        self.assertTrue(any(r.get("name") == "Post Recovery Client" for r in records))

    def test_complete_final_e2e_suite_report(self):
        """Validates programmatic execution of the full final validation suite with report export."""
        report_path = os.path.join(self.test_dir, "reports", "final_test_report.json")
        initial_orders = [{"name": "E2E Suite User", "food": "Salad"}]
        with open(self.target_data_file, "w", encoding="utf-8") as f:
            json.dump(initial_orders, f)

        report = execute_final_test_suite(
            base_url=self.app_url,
            data_file=self.target_data_file,
            backup_dirs=[self.backups_dir],
            report_file=report_path
        )

        self.assertEqual(report["overall_verdict"], "PASS")
        self.assertTrue(report["acceptance_criteria_met"]["failure_is_detected"])
        self.assertTrue(report["acceptance_criteria_met"]["recovery_is_successful"])
        self.assertTrue(report["acceptance_criteria_met"]["application_operational_again"])
        self.assertTrue(os.path.exists(report_path))

    def test_cli_final_test_runner(self):
        """Tests scripts/run_final_test.py CLI command execution and JSON report generation."""
        script_path = os.path.join(REPO_ROOT, "scripts", "run_final_test.py")
        report_path = os.path.join(self.test_dir, "cli_report.json")

        sample = [{"name": "CLI Final User", "food": "Pizza"}]
        with open(self.target_data_file, "w", encoding="utf-8") as f:
            json.dump(sample, f)

        proc = subprocess.run(
            [
                sys.executable,
                script_path,
                "--url", self.app_url,
                "--target", self.target_data_file,
                "--backup-dirs", self.backups_dir,
                "--report-file", report_path
            ],
            capture_output=True,
            text=True
        )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("FINAL DISASTER RECOVERY VALIDATION REPORT - ISSUE #12", proc.stdout)
        self.assertIn("Overall Verdict                 : PASS", proc.stdout)
        self.assertTrue(os.path.exists(report_path))


if __name__ == "__main__":
    unittest.main()
