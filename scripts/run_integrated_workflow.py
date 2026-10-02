"""
Integrated Disaster Recovery System Workflow Orchestrator.
DevOps-Based Disaster Recovery System - Issue #11.

Connects and validates all core components in a unified end-to-end integration workflow:
- Component 1 (Infrastructure & App): Verifies Flask application is running, reachable, and orders endpoint is functional.
- Component 2 (Monitoring): Validates Prometheus /metrics and /health endpoints report healthy operational status (app_health_status 1, status: UP).
- Component 3 (Backup): Executes automated backup and validates snapshot schema and JSON integrity.
- Component 4 (Failure Simulation & Detection): Injects failure (POST /simulate-failure + corrupts/deletes data), confirms monitoring detects outage (status: DOWN 503, app_health_status 0).
- Component 5 (Recovery): Executes disaster recovery to restore data and re-activate application state.
- Component 6 (Post-Recovery Verification): Asserts system is completely restored to operational state (status: UP 200, app_health_status 1, orders data intact).
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
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


def log_step(component_id, title):
    print("\n" + "=" * 76)
    print(f"[{timestamp()}] [COMPONENT {component_id}] {title}")
    print("=" * 76)


def check_app_functional(base_url, data_file=DEFAULT_TARGET_FILE, create_test_order=True, timeout=5):
    """Component 1: Verifies Flask application availability and tests order placement."""
    base_url = base_url.rstrip("/")
    # 1. Probe home page
    try:
        req = urllib.request.Request(f"{base_url}/")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"[{timestamp()}] Home page returned unexpected status: {resp.status}")
                return False
    except Exception as e:
        print(f"[{timestamp()}] Failed to reach application home page: {e}")
        return False

    # 2. Optionally place an order through /order endpoint
    if create_test_order:
        try:
            form_payload = urllib.parse.urlencode({
                "name": "Integration Tester",
                "mobile": "9998881234",
                "food": "Margherita Pizza",
                "quantity": "2"
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{base_url}/order",
                data=form_payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    print(f"[{timestamp()}] /order endpoint returned status: {resp.status}")
                    return False
        except Exception as e:
            print(f"[{timestamp()}] Failed to submit order: {e}")
            return False

    return True


def check_monitoring_telemetry(base_url, expect_healthy=True, timeout=5):
    """Component 2: Probes /health and /metrics endpoints to verify monitoring status."""
    base_url = base_url.rstrip("/")
    health_url = f"{base_url}/health"
    metrics_url = f"{base_url}/metrics"

    actual_health_ok = False
    http_code = 0
    health_body = {}

    try:
        req = urllib.request.Request(health_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            http_code = resp.status
            health_body = json.loads(resp.read().decode("utf-8"))
            if http_code == 200 and health_body.get("status") == "UP":
                actual_health_ok = True
    except urllib.error.HTTPError as err:
        http_code = err.code
        try:
            health_body = json.loads(err.read().decode("utf-8"))
        except Exception:
            health_body = {"error": str(err)}
        actual_health_ok = False
    except Exception as e:
        print(f"[{timestamp()}] Monitoring probe error on {health_url}: {e}")
        return False

    # Probe Prometheus metrics
    metrics_status = None
    try:
        req = urllib.request.Request(metrics_url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            match = re.search(r"^app_health_status\s+([01])", body, re.MULTILINE)
            if match:
                metrics_status = int(match.group(1))
    except Exception as e:
        print(f"[{timestamp()}] Prometheus scrape error on {metrics_url}: {e}")
        return False

    if expect_healthy:
        is_valid = (actual_health_ok and http_code == 200 and metrics_status == 1)
        print(f"Health Probe: HTTP {http_code}, status={health_body.get('status')}; Metrics Probe: app_health_status={metrics_status}")
        return is_valid
    else:
        is_valid = (not actual_health_ok and http_code == 503 and metrics_status == 0)
        print(f"Failure Health Probe: HTTP {http_code} (Expected 503); Metrics Probe: app_health_status={metrics_status} (Expected 0)")
        return is_valid


def execute_backup_workflow(data_file=DEFAULT_TARGET_FILE, backup_dir=None):
    """Component 3: Triggers automated backup and validates snapshot data integrity."""
    if backup_dir is None:
        backup_dir = BACKUP_DIR

    backup_path = backup(data_file=data_file, backup_dir=backup_dir)
    if not backup_path or not os.path.exists(backup_path):
        print(f"[{timestamp()}] Backup failed to create file at: {backup_path}")
        return False, None

    # Validate JSON payload integrity
    try:
        with open(backup_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            print(f"[{timestamp()}] Backup payload is not a valid list: {type(data)}")
            return False, backup_path
        print(f"Backup verified at {backup_path} ({len(data)} records).")
        return True, backup_path
    except Exception as e:
        print(f"[{timestamp()}] Backup JSON corruption detected: {e}")
        return False, backup_path


def simulate_outage(base_url, data_file=DEFAULT_TARGET_FILE, timeout=5):
    """Component 4: Simulates application outage and database corruption."""
    base_url = base_url.rstrip("/")
    try:
        req = urllib.request.Request(f"{base_url}/simulate-failure", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
    except Exception as e:
        print(f"[{timestamp()}] Failed to simulate failure: {e}")
        return False

    # Simulate database loss/corruption
    if os.path.exists(data_file):
        os.remove(data_file)
        print(f"[{timestamp()}] Data loss simulated: Removed {data_file}")

    return True


def run_integrated_workflow(base_url=DEFAULT_APP_URL, data_file=DEFAULT_TARGET_FILE,
                            backup_dirs=None, create_test_order=True):
    """Executes the complete integrated disaster recovery workflow across all tiers."""
    results = {
        "component_1_app": False,
        "component_2_monitoring": False,
        "component_3_backup": False,
        "component_4_failure_detection": False,
        "component_5_recovery": False,
        "component_6_post_verification": False,
        "overall_success": False
    }

    if backup_dirs is None:
        backup_dirs = DEFAULT_BACKUP_DIRS

    primary_backup_dir = backup_dirs[0] if backup_dirs else BACKUP_DIR

    # --------------------------------------------------------------------------
    # Component 1: Application and Infrastructure Reachability
    # --------------------------------------------------------------------------
    log_step(1, "Infrastructure & Application Tier Verification")
    app_ok = check_app_functional(base_url, data_file=data_file, create_test_order=create_test_order)
    if not app_ok:
        print(f"[{timestamp()}] Application functional check failed.")
        return results
    results["component_1_app"] = True
    print(f"[{timestamp()}] Application and ordering endpoints operational.")

    # --------------------------------------------------------------------------
    # Component 2: Monitoring & Health Status
    # --------------------------------------------------------------------------
    log_step(2, "Monitoring Tier Verification (Prometheus & Health Probe)")
    monitoring_ok = check_monitoring_telemetry(base_url, expect_healthy=True)
    if not monitoring_ok:
        print(f"[{timestamp()}] Baseline monitoring verification failed.")
        return results
    results["component_2_monitoring"] = True
    print(f"[{timestamp()}] Monitoring telemetry confirmed healthy state (UP, 1).")

    # --------------------------------------------------------------------------
    # Component 3: Backup System Integration
    # --------------------------------------------------------------------------
    log_step(3, "Backup Tier Execution & Snapshot Integrity Validation")
    backup_ok, backup_path = execute_backup_workflow(data_file=data_file, backup_dir=primary_backup_dir)
    if not backup_ok:
        print(f"[{timestamp()}] Backup workflow execution failed.")
        return results
    results["component_3_backup"] = True

    # --------------------------------------------------------------------------
    # Component 4: Failure Simulation & Outage Detection
    # --------------------------------------------------------------------------
    log_step(4, "Failure Simulation & Outage Detection Verification")
    outage_simulated = simulate_outage(base_url, data_file=data_file)
    if not outage_simulated:
        print(f"[{timestamp()}] Outage simulation failed.")
        return results

    time.sleep(0.1)
    detection_ok = check_monitoring_telemetry(base_url, expect_healthy=False)
    if not detection_ok:
        print(f"[{timestamp()}] Outage was not detected by monitoring probes.")
        return results
    results["component_4_failure_detection"] = True
    print(f"[{timestamp()}] Outage successfully detected across monitoring endpoints.")

    # --------------------------------------------------------------------------
    # Component 5: Disaster Recovery Execution
    # --------------------------------------------------------------------------
    log_step(5, "Disaster Recovery Execution (Data Restore + Health Recovery)")
    rec_result = recover(
        target_path=data_file,
        backup_dirs=backup_dirs,
        app_url=base_url,
        restore_health=True
    )
    if not rec_result["success"] or not rec_result["data_restored"] or not rec_result["app_recovered"]:
        print(f"[{timestamp()}] Recovery execution reported failure: {rec_result}")
        return results
    results["component_5_recovery"] = True
    print(f"[{timestamp()}] Recovery orchestrator restored data and re-activated application.")

    # --------------------------------------------------------------------------
    # Component 6: Post-Recovery End-to-End Verification
    # --------------------------------------------------------------------------
    log_step(6, "Post-Recovery Verification & Data Integrity Confirmation")
    restored_monitoring_ok = check_monitoring_telemetry(base_url, expect_healthy=True)

    data_intact = False
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                content = json.load(f)
            data_intact = isinstance(content, list) and len(content) > 0
            print(f"Restored orders records count: {len(content)}")
        except Exception as e:
            print(f"Error reading restored data file: {e}")

    if restored_monitoring_ok and data_intact:
        results["component_6_post_verification"] = True
        results["overall_success"] = True
        print(f"\n[{timestamp()}] INTEGRATED WORKFLOW COMPLETED SUCCESSFULLY!")
    else:
        print(f"[{timestamp()}] Post-recovery verification failed.")

    return results


def main():
    parser = argparse.ArgumentParser(description="Integrated Disaster Recovery Workflow Runner")
    parser.add_argument("--url", default=DEFAULT_APP_URL, help="Base application URL")
    parser.add_argument("--target", default=DEFAULT_TARGET_FILE, help="Path for orders data file")
    parser.add_argument("--backup-dirs", help="Comma-separated backup directory paths")
    parser.add_argument("--no-order", action="store_true", help="Do not place synthetic order prior to backup")

    args = parser.parse_args()
    dirs = [d.strip() for d in args.backup_dirs.split(",")] if args.backup_dirs else DEFAULT_BACKUP_DIRS

    summary = run_integrated_workflow(
        base_url=args.url,
        data_file=args.target,
        backup_dirs=dirs,
        create_test_order=not args.no_order
    )

    print("\n" + "=" * 76)
    print("INTEGRATED DISASTER RECOVERY WORKFLOW SUMMARY")
    print("=" * 76)
    for comp, status in summary.items():
        print(f"  {comp:<35}: {'PASS' if status else 'FAIL'}")
    print("=" * 76)

    sys.exit(0 if summary["overall_success"] else 1)


if __name__ == "__main__":
    main()
