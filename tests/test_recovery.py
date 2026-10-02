"""
Automated unit and integration tests for Disaster Recovery (scripts/recover.py and scripts/restore.py).
Verifies that recovery restores application data, re-establishes service health, and supports CLI usage.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from contextlib import redirect_stdout
from werkzeug.serving import make_server

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as flask_app
from scripts.recover import (
    find_backups,
    get_latest_backup,
    restore_data,
    recover_application,
    recover
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


class TestRecoveryMechanism(unittest.TestCase):
    """Test suite verifying data restoration and application health recovery."""

    @classmethod
    def setUpClass(cls):
        # Start ephemeral test server for Flask app
        flask_app.app.config["TESTING"] = True
        cls.server_thread = EphemeralServerThread(flask_app.app)
        cls.server_thread.start()
        cls.app_url = cls.server_thread.url

        # Wait briefly for server readiness
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server_thread.shutdown()
        cls.server_thread.join(timeout=2)

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.target_file = os.path.join(self.test_dir, "data", "orders.json")
        self.backups_dir = os.path.join(self.test_dir, "backups")
        self.data_backups_dir = os.path.join(self.test_dir, "data", "backups")
        os.makedirs(self.backups_dir, exist_ok=True)
        os.makedirs(self.data_backups_dir, exist_ok=True)

        # Ensure Flask app starts in healthy state for each test
        flask_app.is_healthy = True

    def tearDown(self):
        flask_app.is_healthy = True
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_restore_data_from_backup_file(self):
        """Verifies direct file restoration from a specific backup file."""
        sample_orders = [
            {"name": "Alice", "mobile": "1234567890", "food": "Tacos", "quantity": "3", "date": "2026-10-02 12:00:00"}
        ]
        backup_file = os.path.join(self.backups_dir, "orders_backup_custom.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(sample_orders, f, indent=4)

        result = restore_data(backup_path=backup_file, target_path=self.target_file)
        self.assertEqual(result, self.target_file)
        self.assertTrue(os.path.exists(self.target_file))

        with open(self.target_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored, sample_orders)

    def test_restore_data_discovers_latest_backup(self):
        """Verifies automatic discovery of the most recently modified backup."""
        older_orders = [{"name": "Old", "food": "Salad"}]
        newer_orders = [{"name": "New", "food": "Pizza"}]

        older_file = os.path.join(self.backups_dir, "orders_backup_2026-10-01.json")
        newer_file = os.path.join(self.data_backups_dir, "latest_backup.json")

        with open(older_file, "w", encoding="utf-8") as f:
            json.dump(older_orders, f)
        # Ensure modification time differs
        time.sleep(0.05)
        with open(newer_file, "w", encoding="utf-8") as f:
            json.dump(newer_orders, f)

        result = restore_data(
            target_path=self.target_file,
            backup_dirs=[self.backups_dir, self.data_backups_dir]
        )
        self.assertEqual(result, self.target_file)

        with open(self.target_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored, newer_orders)

    def test_restore_data_when_no_backup_found(self):
        """Verifies graceful handling and output when no backups exist."""
        empty_dir = os.path.join(self.test_dir, "empty_backups")
        os.makedirs(empty_dir, exist_ok=True)

        buf = io.StringIO()
        with redirect_stdout(buf):
            result = restore_data(target_path=self.target_file, backup_dirs=[empty_dir])
        output = buf.getvalue()

        self.assertIsNone(result)
        self.assertIn("NO BACKUP FOUND", output)
        self.assertFalse(os.path.exists(self.target_file))

    def test_restore_data_ignores_corrupted_backup(self):
        """Verifies that invalid/corrupt JSON backup files are rejected."""
        corrupt_file = os.path.join(self.backups_dir, "orders_backup_corrupted.json")
        with open(corrupt_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json corrupted content ")

        valid_orders = [{"name": "Valid", "food": "Soup"}]
        valid_file = os.path.join(self.backups_dir, "orders_backup_valid.json")
        with open(valid_file, "w", encoding="utf-8") as f:
            json.dump(valid_orders, f)

        result = restore_data(target_path=self.target_file, backup_dirs=[self.backups_dir])
        self.assertEqual(result, self.target_file)

        with open(self.target_file, "r", encoding="utf-8") as f:
            restored = json.load(f)
        self.assertEqual(restored, valid_orders)

    def test_recover_application_health(self):
        """Verifies that recovering application health restores status from DOWN to UP."""
        # 1. Simulate failure via POST /simulate-failure
        req_fail = urllib.request.Request(f"{self.app_url}/simulate-failure", data=b"{}", method="POST")
        with urllib.request.urlopen(req_fail) as resp:
            self.assertEqual(resp.status, 200)

        # 2. Confirm service reports 503 DOWN
        try:
            with urllib.request.urlopen(f"{self.app_url}/health") as resp:
                self.fail("Expected 503 error, but got status 200")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 503)
            body = json.loads(err.read().decode("utf-8"))
            self.assertEqual(body.get("status"), "DOWN")

        # 3. Trigger recovery using recover_application
        recovered = recover_application(app_url=self.app_url)
        self.assertTrue(recovered)

        # 4. Verify service reports 200 UP
        with urllib.request.urlopen(f"{self.app_url}/health") as resp:
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(body.get("status"), "UP")

    def test_full_recovery_e2e(self):
        """End-to-end test: Simulates catastrophic outage (wiped data + DOWN app) and verifies full recovery."""
        # Create backup with production orders
        saved_orders = [
            {"name": "E2E User", "mobile": "9998887777", "food": "Burrito", "quantity": "2", "date": "2026-10-02 18:00:00"}
        ]
        backup_file = os.path.join(self.backups_dir, "orders_backup_prod.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(saved_orders, f, indent=4)

        # Disaster scenario: data is deleted and application health fails
        if os.path.exists(self.target_file):
            os.remove(self.target_file)
        flask_app.is_healthy = False

        # Execute complete recovery
        result = recover(
            backup_path=backup_file,
            target_path=self.target_file,
            app_url=self.app_url,
            restore_health=True
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["data_restored"])
        self.assertTrue(result["app_recovered"])
        self.assertEqual(result["target_file"], self.target_file)

        # Confirm data file restored and intact
        with open(self.target_file, "r", encoding="utf-8") as f:
            restored_orders = json.load(f)
        self.assertEqual(restored_orders, saved_orders)

        # Confirm app health is UP
        with urllib.request.urlopen(f"{self.app_url}/health") as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("status"), "UP")

    def test_cli_recovery_execution(self):
        """Verifies running scripts/recover.py via CLI command."""
        script_path = os.path.join(REPO_ROOT, "scripts", "recover.py")

        orders = [{"name": "CLI User", "food": "Burger"}]
        backup_file = os.path.join(self.backups_dir, "orders_backup_cli.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(orders, f)

        # Simulate failure first
        flask_app.is_healthy = False

        proc = subprocess.run(
            [
                sys.executable,
                script_path,
                "--backup", backup_file,
                "--target", self.target_file,
                "--url", self.app_url
            ],
            capture_output=True,
            text=True
        )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("RESTORE SUCCESSFUL", proc.stdout)
        self.assertIn("APPLICATION HEALTH RESTORED", proc.stdout)
        self.assertTrue(os.path.exists(self.target_file))
        self.assertTrue(flask_app.is_healthy)

    def test_cli_data_only_flag(self):
        """Verifies running scripts/recover.py with --data-only flag."""
        script_path = os.path.join(REPO_ROOT, "scripts", "recover.py")

        orders = [{"name": "Data Only", "food": "Pasta"}]
        backup_file = os.path.join(self.backups_dir, "orders_backup_data.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(orders, f)

        proc = subprocess.run(
            [
                sys.executable,
                script_path,
                "--backup", backup_file,
                "--target", self.target_file,
                "--data-only"
            ],
            capture_output=True,
            text=True
        )

        self.assertEqual(proc.returncode, 0)
        self.assertIn("RESTORE SUCCESSFUL", proc.stdout)
        self.assertTrue(os.path.exists(self.target_file))


if __name__ == "__main__":
    unittest.main()
