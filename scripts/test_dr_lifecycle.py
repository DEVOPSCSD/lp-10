"""
Disaster Recovery Failure & Recovery Lifecycle Automation Script.
DevOps-Based Disaster Recovery System - Issue #10.

Demonstrates and verifies the complete end-to-end failure detection and recovery lifecycle:
1. Baseline Verification: Ensures the application is running and healthy (GET /health -> 200 UP, GET /metrics -> 1).
2. Failure Simulation: Injects failure (POST /simulate-failure and simulates data corruption).
3. Failure Detection: Verifies monitoring probes detect the outage (GET /health -> 503 DOWN, GET /metrics -> 0).
4. Recovery Execution: Triggers automated disaster recovery via scripts.recover.recover().
5. Restoration Verification: Confirms application health is restored (200 UP, metrics 1) and data integrity is intact.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from scripts.backup import backup, BACKUP_DIR
from scripts.recover import recover, DEFAULT_TARGET_FILE, DEFAULT_APP_URL, DEFAULT_BACKUP_DIRS


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_step(step_num, title):
    print("\n" + "=" * 70)
    print(f"[{timestamp()}] [STEP {step_num}] {title}")
    print("=" * 70)


def check_health(base_url, timeout=5):
    """Probes the /health endpoint and returns (is_up, status_code, data)."""
    health_url = f"{base_url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(health_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("status") == "UP", resp.status, data)
    except urllib.error.HTTPError as err:
        try:
            data = json.loads(err.read().decode("utf-8"))
        except Exception:
            data = {"error": str(err)}
        return (False, err.code, data)
    except Exception as e:
        return (False, 0, {"error": str(e)})


def check_metrics(base_url, timeout=5):
    """Probes the /metrics Prometheus endpoint and extracts app_health_status value."""
    metrics_url = f"{base_url.rstrip('/')}/metrics"
    try:
        req = urllib.request.Request(metrics_url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            match = re.search(r"^app_health_status\s+([01])", body, re.MULTILINE)
            if match:
                return int(match.group(1))
            return None
    except Exception:
        return None


def trigger_simulate_failure(base_url, timeout=5):
    """Posts to /simulate-failure to mark application health as DOWN."""
    fail_url = f"{base_url.rstrip('/')}/simulate-failure"
    req = urllib.request.Request(fail_url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[{timestamp()}] Failed to simulate failure: {e}")
        return False


def run_dr_lifecycle(base_url=DEFAULT_APP_URL, data_file=DEFAULT_TARGET_FILE,
                     backup_dirs=None, auto_create_backup=True):
    """Executes the complete disaster recovery verification lifecycle."""
    report = {
        "baseline_healthy": False,
        "failure_simulated": False,
        "failure_detected": False,
        "recovery_triggered": False,
        "restoration_verified": False,
        "overall_success": False
    }

    if backup_dirs is None:
        backup_dirs = DEFAULT_BACKUP_DIRS

    # Step 1: Ensure initial backup exists
    log_step(1, "Pre-requisite Baseline & Backup Preparation")
    is_up, code, health_data = check_health(base_url)
    metrics_status = check_metrics(base_url)
    print(f"Baseline Health Check: HTTP {code}, payload: {health_data}")
    print(f"Baseline Metrics Probe: app_health_status = {metrics_status}")

    if not is_up or metrics_status != 1:
        print(f"[{timestamp()}] Application is not healthy at baseline. Status: {health_data}")
        return report

    report["baseline_healthy"] = True

    if auto_create_backup:
        print(f"[{timestamp()}] Ensuring valid backup exists before failure simulation...")
        target_backup_dir = backup_dirs[0] if backup_dirs else BACKUP_DIR
        backup_created = backup(data_file=data_file, backup_dir=target_backup_dir)
        print(f"[{timestamp()}] Pre-failure backup ensured at: {backup_created}")

    # Read current data for verification comparison later
    expected_data = None
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                expected_data = json.load(f)
        except Exception:
            pass

    # Step 2: Simulate Failure
    log_step(2, "Simulating System Failure & Data Corruption")
    failure_simulated = trigger_simulate_failure(base_url)
    if not failure_simulated:
        print(f"[{timestamp()}] Failed to trigger /simulate-failure.")
        return report

    # Also simulate data loss / corruption
    if os.path.exists(data_file):
        os.remove(data_file)
        print(f"[{timestamp()}] Data loss simulated: Deleted {data_file}")

    report["failure_simulated"] = True
    print(f"[{timestamp()}] Failure injection completed.")

    # Step 3: Verify Failure Detection
    log_step(3, "Verifying Outage Detection via Health & Telemetry Probes")
    time.sleep(0.1)
    is_up_after_fail, code_after_fail, data_after_fail = check_health(base_url)
    metrics_after_fail = check_metrics(base_url)

    print(f"Post-Failure Health Check: HTTP {code_after_fail} (Expected 503), payload: {data_after_fail}")
    print(f"Post-Failure Metrics Probe: app_health_status = {metrics_after_fail} (Expected 0)")

    if code_after_fail == 503 and not is_up_after_fail and metrics_after_fail == 0:
        print(f"[{timestamp()}] Failure successfully detected by both /health and Prometheus /metrics!")
        report["failure_detected"] = True
    else:
        print(f"[{timestamp()}] Failure detection check failed.")
        return report

    # Step 4: Trigger Disaster Recovery
    log_step(4, "Triggering Disaster Recovery Orchestrator")
    recovery_result = recover(
        target_path=data_file,
        backup_dirs=backup_dirs,
        app_url=base_url,
        restore_health=True
    )
    print(f"Recovery Execution Result: {recovery_result}")

    if not recovery_result["success"] or not recovery_result["data_restored"]:
        print(f"[{timestamp()}] Disaster recovery execution reported failure.")
        return report

    report["recovery_triggered"] = True

    # Step 5: Verify Post-Recovery Restoration
    log_step(5, "Verifying Post-Recovery Application & Data Restoration")
    is_up_recovered, code_recovered, data_recovered = check_health(base_url)
    metrics_recovered = check_metrics(base_url)

    print(f"Restored Health Check: HTTP {code_recovered} (Expected 200), payload: {data_recovered}")
    print(f"Restored Metrics Probe: app_health_status = {metrics_recovered} (Expected 1)")

    # Verify data integrity
    data_intact = False
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                restored_content = json.load(f)
            if expected_data is not None:
                data_intact = (restored_content == expected_data)
            else:
                data_intact = isinstance(restored_content, list)
            print(f"Data File Integrity: Restored successfully with {len(restored_content)} records.")
        except Exception as e:
            print(f"Data verification error: {e}")

    if is_up_recovered and code_recovered == 200 and metrics_recovered == 1 and data_intact:
        print(f"\n[{timestamp()}] SUCCESS: Application and data fully restored to operational state!")
        report["restoration_verified"] = True
        report["overall_success"] = True
    else:
        print(f"[{timestamp()}] Post-recovery verification failed.")

    return report


def main():
    parser = argparse.ArgumentParser(description="Disaster Recovery Failure and Recovery Demonstration")
    parser.add_argument("--url", default=DEFAULT_APP_URL, help="Base application URL")
    parser.add_argument("--target", default=DEFAULT_TARGET_FILE, help="Path for application orders file")
    parser.add_argument("--backup-dirs", help="Comma-separated backup directories")
    parser.add_argument("--skip-auto-backup", action="store_true", help="Do not create backup prior to test")

    args = parser.parse_args()
    dirs = [d.strip() for d in args.backup_dirs.split(",")] if args.backup_dirs else DEFAULT_BACKUP_DIRS

    result = run_dr_lifecycle(
        base_url=args.url,
        data_file=args.target,
        backup_dirs=dirs,
        auto_create_backup=not args.skip_auto_backup
    )

    print("\n" + "=" * 70)
    print("DISASTER RECOVERY LIFECYCLE SUMMARY REPORT")
    print("=" * 70)
    for k, v in result.items():
        print(f"  {k:<25}: {'PASS' if v else 'FAIL'}")
    print("=" * 70)

    sys.exit(0 if result["overall_success"] else 1)


if __name__ == "__main__":
    main()
