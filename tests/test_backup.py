"""
Unit tests for the disaster recovery backup script (scripts/backup.py).
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.backup import perform_backup


class TestBackupScript(unittest.TestCase):
    """Test suite for backup functionality."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.source_file = os.path.join(self.test_dir, "orders.json")
        self.backup_folder = os.path.join(self.test_dir, "backups")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_backup_source_not_found(self):
        """Verifies error handling when source orders file does not exist."""
        f = io.StringIO()
        with redirect_stdout(f):
            result = perform_backup(
                source=self.source_file,
                backup_folder=self.backup_folder
            )
        output = f.getvalue()

        self.assertIsNone(result)
        self.assertIn("ERROR: orders.json not found", output)

    def test_backup_success_with_valid_orders(self):
        """Verifies successful backup creation and data integrity."""
        dummy_orders = [
            {
                "name": "John Doe",
                "mobile": "9876543210",
                "food": "Burger",
                "quantity": "2",
                "date": "2026-09-12 12:00:00"
            }
        ]
        with open(self.source_file, "w", encoding="utf-8") as file:
            json.dump(dummy_orders, file)

        f = io.StringIO()
        with redirect_stdout(f):
            backup_path = perform_backup(
                source=self.source_file,
                backup_folder=self.backup_folder
            )
        output = f.getvalue()

        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))
        self.assertIn("BACKUP SUCCESSFUL", output)

        # Verify content of backup matches original
        with open(backup_path, "r", encoding="utf-8") as file:
            backed_up_data = json.load(file)
        self.assertEqual(backed_up_data, dummy_orders)

    def test_cli_execution(self):
        """Verifies running the script directly as a CLI command."""
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        script_path = os.path.join(repo_root, "scripts", "backup.py")

        # Run within isolated temp directory to prevent polluting repository backups/
        test_data_dir = os.path.join(self.test_dir, "data")
        os.makedirs(test_data_dir, exist_ok=True)
        with open(os.path.join(test_data_dir, "orders.json"), "w", encoding="utf-8") as f:
            f.write("[]")

        result = subprocess.run(
            [sys.executable, script_path],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("BACKUP SUCCESSFUL", result.stdout)


if __name__ == "__main__":
    unittest.main()
