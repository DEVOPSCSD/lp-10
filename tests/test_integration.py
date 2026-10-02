"""
Automated Integration Tests for the Complete Disaster Recovery System (Issue #11).
Verifies:
1. Communication across App, Monitoring, Backup, and Recovery tiers.
2. End-to-end execution of the integrated disaster recovery workflow.
3. Edge case handling (missing backups, corrupted snapshots, unreachable services).
4. CLI execution of scripts/run_integrated_workflow.py.
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
from scripts.run_integrated_workflow import (
    check_app_functional,
    check_monitoring_telemetry,
    execute_backup_workflow,
    simulate_outage,
    run_integrated_workflow
)
from scripts.recover import recover


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


class TestSystemIntegration(unittest.TestCase):
    """Integration test suite across App, Monitoring, Backup, and Recovery components."""

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

    def test_tier_communication_app_and_monitoring(self):
        """Verifies communication between Application tier and Monitoring tier."""
        # 1. Ensure app is operational and accepts orders
        app_ok = check_app_functional(self.app_url, data_file=self.target_data_file, create_test_order=True)
        self.assertTrue(app_ok)

        # 2. Confirm monitoring tier reflects healthy status
        monitoring_healthy = check_monitoring_telemetry(self.app_url, expect_healthy=True)
        self.assertTrue(monitoring_healthy)

        # 3. Simulate failure and confirm monitoring tier captures outage
        outage_ok = simulate_outage(self.app_url, data_file=self.target_data_file)
        self.assertTrue(outage_ok)

        monitoring_outage = check_monitoring_telemetry(self.app_url, expect_healthy=False)
        self.assertTrue(monitoring_outage)

    def test_tier_communication_backup_and_recovery(self):
        """Verifies data communication between Backup tier and Recovery tier."""
        # Write known data
        test_orders = [{"name": "Backup Tier Test", "food": "Pasta", "quantity": "1"}]
        with open(self.target_data_file, "w", encoding="utf-8") as f:
            json.dump(test_orders, f)

        # Execute backup
        backup_success, backup_path = execute_backup_workflow(
            data_file=self.target_data_file,
            backup_dir=self.backups_dir
        )
        self.assertTrue(backup_success)
        self.assertTrue(os.path.exists(backup_path))

        # Wipe target data
        os.remove(self.target_data_file)
        self.assertFalse(os.path.exists(self.target_data_file))

        # Recover data
        rec_res = recover(
            target_path=self.target_data_file,
            backup_dirs=[self.backups_dir],
            app_url=self.app_url,
            restore_health=True
        )
        self.assertTrue(rec_res["success"])
        self.assertTrue(rec_res["data_restored"])
        self.assertTrue(os.path.exists(self.target_data_file))

        with open(self.target_data_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored, test_orders)

    def test_full_integrated_workflow_execution(self):
        """Executes full automated workflow orchestrating all 6 components."""
        summary = run_integrated_workflow(
            base_url=self.app_url,
            data_file=self.target_data_file,
            backup_dirs=[self.backups_dir],
            create_test_order=True
        )

        self.assertTrue(summary["component_1_app"])
        self.assertTrue(summary["component_2_monitoring"])
        self.assertTrue(summary["component_3_backup"])
        self.assertTrue(summary["component_4_failure_detection"])
        self.assertTrue(summary["component_5_recovery"])
        self.assertTrue(summary["component_6_post_verification"])
        self.assertTrue(summary["overall_success"])

    def test_edge_case_missing_backup(self):
        """Verifies recovery handles missing backups gracefully without crash."""
        empty_dir = os.path.join(self.test_dir, "non_existent_backups")
        os.makedirs(empty_dir, exist_ok=True)

        res = recover(
            target_path=self.target_data_file,
            backup_dirs=[empty_dir],
            app_url=self.app_url,
            restore_health=True
        )

        self.assertFalse(res["success"])
        self.assertFalse(res["data_restored"])
        self.assertIn("No valid backup found", res["message"])

    def test_edge_case_corrupted_backup(self):
        """Verifies recovery rejects corrupted JSON files during integration recovery."""
        corrupt_backup = os.path.join(self.backups_dir, "latest_backup.json")
        with open(corrupt_backup, "w", encoding="utf-8") as f:
            f.write("<<< corrupted json content >>>")

        res = recover(
            target_path=self.target_data_file,
            backup_dirs=[self.backups_dir],
            app_url=self.app_url,
            restore_health=True
        )

        self.assertFalse(res["success"])
        self.assertFalse(res["data_restored"])

    def test_cli_integrated_workflow_runner(self):
        """Tests running scripts/run_integrated_workflow.py via subprocess CLI."""
        script_path = os.path.join(REPO_ROOT, "scripts", "run_integrated_workflow.py")

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
        self.assertIn("INTEGRATED DISASTER RECOVERY WORKFLOW SUMMARY", proc.stdout)
        self.assertIn("overall_success                    : PASS", proc.stdout)
        self.assertTrue(flask_app.is_healthy)


if __name__ == "__main__":
    unittest.main()
