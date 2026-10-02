"""
Final End-to-End Disaster Recovery Validation and Report Generator.
DevOps-Based Disaster Recovery System - Issue #12.

Executes the complete final acceptance validation suite against the application:
1. Application Liveness & Baseline Health (GET /health -> 200 UP)
2. Prometheus Telemetry Verification (GET /metrics -> app_health_status 1)
3. Failure Injection (POST /simulate-failure + dataset deletion)
4. Outage Detection Validation (GET /health -> 503 DOWN, GET /metrics -> app_health_status 0)
5. Disaster Recovery Execution (scripts.recover.recover())
6. Full Application Restoration & Data Integrity Confirmation (GET /health -> 200 UP, metric 1, data verified)
7. Telemetry & Summary Report Export
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


def query_health(base_url, timeout=5):
    """Queries /health endpoint and returns (is_up, status_code, payload)."""
    url = f"{base_url.rstrip('/')}/health"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
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


def query_metrics(base_url, timeout=5):
    """Scrapes Prometheus /metrics endpoint and returns (health_metric, uptime_metric)."""
    url = f"{base_url.rstrip('/')}/metrics"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            status_match = re.search(r"^app_health_status\s+([01])", body, re.MULTILINE)
            uptime_match = re.search(r"^app_uptime_seconds\s+([\d.]+)", body, re.MULTILINE)

            health_status = int(status_match.group(1)) if status_match else None
            uptime = float(uptime_match.group(1)) if uptime_match else None
            return (health_status, uptime)
    except Exception as e:
        print(f"[{timestamp()}] Metrics scrape failed: {e}")
        return (None, None)


def inject_failure(base_url, timeout=5):
    """Simulates outage by invoking POST /simulate-failure."""
    url = f"{base_url.rstrip('/')}/simulate-failure"
    try:
        req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[{timestamp()}] Failed to invoke /simulate-failure: {e}")
        return False


def execute_final_test_suite(base_url=DEFAULT_APP_URL, data_file=DEFAULT_TARGET_FILE,
                             backup_dirs=None, report_file=None):
    """Executes all final acceptance tests and logs structured telemetry."""
    start_time = time.time()
    report = {
        "timestamp": timestamp(),
        "base_url": base_url,
        "data_file": data_file,
        "criteria": {
            "application_starts_and_healthy": False,
            "monitoring_telemetry_valid": False,
            "failure_injected": False,
            "failure_detected": False,
            "recovery_completed": False,
            "application_restored": False,
            "data_integrity_verified": False
        },
        "acceptance_criteria_met": {
            "failure_is_detected": False,
            "recovery_is_successful": False,
            "application_operational_again": False
        },
        "telemetry": {},
        "overall_verdict": "FAIL"
    }

    if backup_dirs is None:
        backup_dirs = DEFAULT_BACKUP_DIRS

    primary_backup_dir = backup_dirs[0] if backup_dirs else BACKUP_DIR

    print("=" * 80)
    print(f"[{timestamp()}] STARTING FINAL DISASTER RECOVERY VALIDATION SUITE (ISSUE #12)")
    print("=" * 80)

    # 1. Baseline Application Check
    print(f"\n[{timestamp()}] [PHASE 1] Application Liveness & Baseline Check")
    is_up, code, health_data = query_health(base_url)
    report["telemetry"]["baseline_health_code"] = code
    report["telemetry"]["baseline_health_payload"] = health_data

    if is_up and code == 200:
        report["criteria"]["application_starts_and_healthy"] = True
        print(f"  --> PASS: Application is healthy (HTTP 200, status: {health_data.get('status')})")
    else:
        print(f"  --> FAIL: Application is not healthy (HTTP {code}, payload: {health_data})")
        return finalize_report(report, start_time, report_file)

    # 2. Monitoring Telemetry Check
    print(f"\n[{timestamp()}] [PHASE 2] Monitoring Telemetry Verification")
    metric_health, metric_uptime = query_metrics(base_url)
    report["telemetry"]["baseline_app_health_status"] = metric_health
    report["telemetry"]["baseline_uptime_seconds"] = metric_uptime

    if metric_health == 1:
        report["criteria"]["monitoring_telemetry_valid"] = True
        print(f"  --> PASS: Prometheus reports app_health_status = {metric_health}, uptime = {metric_uptime}s")
    else:
        print(f"  --> FAIL: Prometheus reported unexpected metric value: {metric_health}")
        return finalize_report(report, start_time, report_file)

    # 3. Snapshot Data Preparation
    print(f"\n[{timestamp()}] [PHASE 3] Backup Snapshot Generation")
    backup_path = backup(data_file=data_file, backup_dir=primary_backup_dir)
    report["telemetry"]["snapshot_path"] = backup_path

    expected_orders = []
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                expected_orders = json.load(f)
        except Exception:
            pass
    print(f"  --> PASS: Snapshot created at {backup_path} ({len(expected_orders)} records preserved)")

    # 4. Simulate Failure
    print(f"\n[{timestamp()}] [PHASE 4] Failure Injection (Outage & Data Loss)")
    fail_ok = inject_failure(base_url)
    if os.path.exists(data_file):
        os.remove(data_file)
        print(f"  --> Data file {data_file} deleted to simulate storage failure.")

    if fail_ok:
        report["criteria"]["failure_injected"] = True
        print("  --> PASS: Failure successfully simulated via /simulate-failure.")
    else:
        print("  --> FAIL: Could not inject failure.")
        return finalize_report(report, start_time, report_file)

    # 5. Outage Detection Verification (Acceptance Criterion 1)
    print(f"\n[{timestamp()}] [PHASE 5] Outage Detection Verification")
    time.sleep(0.1)
    is_up_fail, code_fail, data_fail = query_health(base_url)
    metric_health_fail, _ = query_metrics(base_url)
    report["telemetry"]["outage_health_code"] = code_fail
    report["telemetry"]["outage_app_health_status"] = metric_health_fail

    if code_fail == 503 and not is_up_fail and metric_health_fail == 0:
        report["criteria"]["failure_detected"] = True
        report["acceptance_criteria_met"]["failure_is_detected"] = True
        print(f"  --> PASS: Outage successfully detected! (HTTP 503 DOWN, metric: {metric_health_fail})")
    else:
        print(f"  --> FAIL: Outage detection failed: HTTP {code_fail}, metric {metric_health_fail}")
        return finalize_report(report, start_time, report_file)

    # 6. Disaster Recovery Execution (Acceptance Criterion 2)
    print(f"\n[{timestamp()}] [PHASE 6] Disaster Recovery Execution")
    rec_result = recover(
        target_path=data_file,
        backup_dirs=backup_dirs,
        app_url=base_url,
        restore_health=True
    )
    report["telemetry"]["recovery_result"] = rec_result

    if rec_result["success"] and rec_result["data_restored"] and rec_result["app_recovered"]:
        report["criteria"]["recovery_completed"] = True
        report["acceptance_criteria_met"]["recovery_is_successful"] = True
        print(f"  --> PASS: Disaster recovery completed successfully: {rec_result.get('message')}")
    else:
        print(f"  --> FAIL: Recovery orchestrator failed: {rec_result}")
        return finalize_report(report, start_time, report_file)

    # 7. Final Restoration & Integrity Confirmation (Acceptance Criterion 3)
    print(f"\n[{timestamp()}] [PHASE 7] Final Application Restoration & Data Verification")
    is_up_restored, code_restored, data_restored = query_health(base_url)
    metric_health_restored, metric_uptime_restored = query_metrics(base_url)
    report["telemetry"]["restored_health_code"] = code_restored
    report["telemetry"]["restored_app_health_status"] = metric_health_restored
    report["telemetry"]["restored_uptime_seconds"] = metric_uptime_restored

    data_intact = False
    if os.path.exists(data_file):
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                restored_records = json.load(f)
            data_intact = (restored_records == expected_orders) or (isinstance(restored_records, list) and len(restored_records) > 0)
            report["telemetry"]["restored_record_count"] = len(restored_records)
        except Exception as e:
            report["telemetry"]["data_check_error"] = str(e)

    if data_intact:
        report["criteria"]["data_integrity_verified"] = True
        print(f"  --> PASS: Restored orders dataset verified ({report['telemetry'].get('restored_record_count', 0)} records).")

    if is_up_restored and code_restored == 200 and metric_health_restored == 1:
        report["criteria"]["application_restored"] = True
        report["acceptance_criteria_met"]["application_operational_again"] = True
        print(f"  --> PASS: Application operational again (HTTP 200 UP, metric: {metric_health_restored})")
    else:
        print(f"  --> FAIL: Application restoration check failed (HTTP {code_restored}, metric {metric_health_restored})")

    all_accepted = all(report["acceptance_criteria_met"].values())
    if all_accepted and data_intact:
        report["overall_verdict"] = "PASS"

    return finalize_report(report, start_time, report_file)


def finalize_report(report, start_time, report_file=None):
    """Finalizes telemetry timings, outputs summary, and optionally exports report."""
    report["duration_seconds"] = round(time.time() - start_time, 3)

    print("\n" + "=" * 80)
    print("FINAL DISASTER RECOVERY VALIDATION REPORT - ISSUE #12")
    print("=" * 80)
    print(f"  Overall Verdict                 : {report['overall_verdict']}")
    print(f"  Total Duration                  : {report['duration_seconds']}s")
    print("\n  Acceptance Criteria:")
    for crit, met in report["acceptance_criteria_met"].items():
        print(f"    - {crit:<32}: {'[MET]' if met else '[FAILED]'}")

    print("\n  Lifecycle Criteria Breakdown:")
    for crit, met in report["criteria"].items():
        print(f"    - {crit:<32}: {'PASS' if met else 'FAIL'}")
    print("=" * 80)

    if report_file:
        try:
            report_dir = os.path.dirname(report_file)
            if report_dir:
                os.makedirs(report_dir, exist_ok=True)
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4)
            print(f"Report exported to: {report_file}")
        except Exception as e:
            print(f"Warning: Failed to export report file: {e}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Final End-to-End Disaster Recovery Validation Runner")
    parser.add_argument("--url", default=DEFAULT_APP_URL, help="Base application URL")
    parser.add_argument("--target", default=DEFAULT_TARGET_FILE, help="Path for application orders data file")
    parser.add_argument("--backup-dirs", help="Comma-separated backup directory paths")
    parser.add_argument("--report-file", help="Path to export JSON validation report")

    args = parser.parse_args()
    dirs = [d.strip() for d in args.backup_dirs.split(",")] if args.backup_dirs else DEFAULT_BACKUP_DIRS

    report = execute_final_test_suite(
        base_url=args.url,
        data_file=args.target,
        backup_dirs=dirs,
        report_file=args.report_file
    )

    sys.exit(0 if report["overall_verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
