"""
Disaster Recovery Recovery & Restoration Orchestrator.
DevOps-Based Disaster Recovery System.

This script executes complete disaster recovery by:
1. Identifying and restoring the latest valid orders backup to data/orders.json.
2. Triggering application health recovery via /simulate-recover and verifying
   that the application health status returns to UP.
"""

import argparse
import glob
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime

DEFAULT_TARGET_FILE = "data/orders.json"
DEFAULT_BACKUP_DIRS = ["data/backups", "backups"]
DEFAULT_APP_URL = os.environ.get("APP_URL", "http://127.0.0.1:5000")


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def find_backups(backup_dirs=None):
    """Discovers all valid JSON backup files across specified backup directories."""
    if backup_dirs is None:
        backup_dirs = DEFAULT_BACKUP_DIRS

    candidate_files = []
    for directory in backup_dirs:
        if not os.path.exists(directory):
            continue
        patterns = [
            os.path.join(directory, "latest_backup.json"),
            os.path.join(directory, "orders_backup_*.json"),
            os.path.join(directory, "*.json")
        ]
        for pattern in patterns:
            for filepath in glob.glob(pattern):
                if os.path.isfile(filepath) and filepath not in candidate_files:
                    candidate_files.append(filepath)

    # Filter out corrupted or unreadable JSON files
    valid_backups = []
    for filepath in candidate_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                json.load(f)
            valid_backups.append(filepath)
        except Exception:
            continue

    # Sort descending by modification time (most recent first)
    valid_backups.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return valid_backups


def get_latest_backup(backup_dirs=None, specific_file=None):
    """Resolves the most appropriate backup file to restore."""
    if specific_file:
        if not os.path.exists(specific_file):
            return None
        try:
            with open(specific_file, "r", encoding="utf-8") as f:
                json.load(f)
            return specific_file
        except Exception:
            return None

    backups = find_backups(backup_dirs)
    if backups:
        return backups[0]
    return None


def restore_data(backup_path=None, target_path=DEFAULT_TARGET_FILE, backup_dirs=None):
    """Restores application orders data from a designated or latest backup file."""
    selected_backup = get_latest_backup(backup_dirs=backup_dirs, specific_file=backup_path)

    if not selected_backup:
        print("NO BACKUP FOUND")
        return None

    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)

    # Ensure source data is valid JSON before copying
    with open(selected_backup, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Atomic write or direct copy
    shutil.copy2(selected_backup, target_path)

    print("================================")
    print("RESTORE SUCCESSFUL")
    print("================================")
    print("Backup file   :", selected_backup)
    print("Restored file :", target_path)
    print("Record count  :", len(data) if isinstance(data, list) else 1)
    print("================================")
    return target_path


def recover_application(app_url=DEFAULT_APP_URL, timeout=5, max_retries=3):
    """Reactivates application health by invoking the recovery endpoint."""
    app_url = app_url.rstrip("/")
    recover_endpoint = f"{app_url}/simulate-recover"
    health_endpoint = f"{app_url}/health"

    print(f"[{timestamp()}] Initiating application recovery request to {recover_endpoint}...")

    success = False
    for attempt in range(1, max_retries + 1):
        try:
            # Trigger recovery via POST
            req = urllib.request.Request(
                recover_endpoint,
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    success = True
                    break
        except Exception as e:
            if attempt < max_retries:
                continue
            else:
                print(f"[{timestamp()}] Could not contact recovery endpoint ({e}).")
                return False

    if not success:
        return False

    # Verify that the health endpoint reports UP
    try:
        req = urllib.request.Request(health_endpoint, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if resp.status == 200 and data.get("status") == "UP":
                print("================================")
                print("APPLICATION HEALTH RESTORED")
                print("================================")
                print("Endpoint :", health_endpoint)
                print("Status   : UP")
                print("Uptime   :", data.get("uptime_seconds", "N/A"), "seconds")
                print("================================")
                return True
            else:
                print(f"[{timestamp()}] Health check returned non-UP status: {data.get('status')}")
                return False
    except Exception as e:
        print(f"[{timestamp()}] Health verification failed ({e}).")
        return False


def recover(backup_path=None, target_path=DEFAULT_TARGET_FILE, backup_dirs=None,
            app_url=DEFAULT_APP_URL, restore_health=True):
    """Executes full recovery procedure: data restoration and application reactivation."""
    results = {
        "success": False,
        "data_restored": False,
        "app_recovered": False,
        "backup_file": None,
        "target_file": target_path,
        "message": ""
    }

    selected_backup = get_latest_backup(backup_dirs=backup_dirs, specific_file=backup_path)
    results["backup_file"] = selected_backup

    restored_target = restore_data(
        backup_path=selected_backup,
        target_path=target_path,
        backup_dirs=backup_dirs
    )
    if not restored_target:
        results["message"] = "Data restoration failed: No valid backup found."
        return results

    results["data_restored"] = True

    if restore_health:
        app_ok = recover_application(app_url=app_url)
        results["app_recovered"] = app_ok
        if app_ok:
            results["success"] = True
            results["message"] = "Disaster recovery completed successfully. Data and health restored."
        else:
            results["message"] = "Data restored, but application health recovery did not succeed."
    else:
        results["success"] = True
        results["message"] = "Data restoration completed successfully (health check skipped)."

    return results


def main():
    parser = argparse.ArgumentParser(description="Disaster Recovery and Restoration Utility")
    parser.add_argument("--backup", help="Path to specific backup file to restore")
    parser.add_argument("--target", default=DEFAULT_TARGET_FILE, help="Path for restored data file")
    parser.add_argument("--backup-dirs", help="Comma-separated backup directories to search")
    parser.add_argument("--url", default=DEFAULT_APP_URL, help="Base application URL for health recovery")
    parser.add_argument("--data-only", action="store_true", help="Restore data file only")
    parser.add_argument("--health-only", action="store_true", help="Trigger health recovery only")

    args = parser.parse_args()

    dirs = [d.strip() for d in args.backup_dirs.split(",")] if args.backup_dirs else DEFAULT_BACKUP_DIRS

    if args.health_only:
        ok = recover_application(app_url=args.url)
        sys.exit(0 if ok else 1)

    if args.data_only:
        res = restore_data(backup_path=args.backup, target_path=args.target, backup_dirs=dirs)
        sys.exit(0 if res else 1)

    result = recover(
        backup_path=args.backup,
        target_path=args.target,
        backup_dirs=dirs,
        app_url=args.url,
        restore_health=True
    )
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
