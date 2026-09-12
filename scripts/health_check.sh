#!/usr/bin/env bash
# ==============================================================================
# Health Check Probe Script
# DevOps-Based Disaster Recovery System
# ==============================================================================
# Queries service health endpoint, verifies HTTP status code and payload health.
# Usage: ./scripts/health_check.sh [TARGET_URL]
# Environment Variables:
#   TARGET_URL     - Endpoint URL (Default: http://localhost:8080/healthz)
#   MAX_RETRIES    - Maximum consecutive retry attempts (Default: 3)
#   RETRY_INTERVAL - Interval in seconds between retries (Default: 2)
#   TIMEOUT_SEC    - HTTP connection timeout in seconds (Default: 5)
# ==============================================================================

set -euo pipefail

TARGET_URL="${1:-${TARGET_URL:-http://localhost:8080/healthz}}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"
TIMEOUT_SEC="${TIMEOUT_SEC:-5}"

timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

log_info() {
    echo "[$(timestamp)] [INFO]  $*"
}

log_warn() {
    echo "[$(timestamp)] [WARN]  $*" >&2
}

log_error() {
    echo "[$(timestamp)] [ERROR] $*" >&2
}

log_info "Initiating health check against: ${TARGET_URL}"
log_info "Configuration: max_retries=${MAX_RETRIES}, timeout=${TIMEOUT_SEC}s, interval=${RETRY_INTERVAL}s"

attempt=1
while [ "${attempt}" -le "${MAX_RETRIES}" ]; do
    log_info "Attempt ${attempt}/${MAX_RETRIES}: Probing ${TARGET_URL}..."

    # Perform request capturing HTTP status and response body
    HTTP_RESPONSE=$(curl -sS -w "\n%{http_code}" --max-time "${TIMEOUT_SEC}" "${TARGET_URL}" 2>/dev/null) || HTTP_STATUS="000"

    if [ "${HTTP_RESPONSE:-}" != "" ]; then
        HTTP_BODY=$(echo "${HTTP_RESPONSE}" | sed '$d')
        HTTP_CODE=$(echo "${HTTP_RESPONSE}" | tail -n1)
    else
        HTTP_BODY=""
        HTTP_CODE="000"
    fi

    if [ "${HTTP_CODE}" = "200" ]; then
        if echo "${HTTP_BODY}" | grep -q '"status"[[:space:]]*:[[:space:]]*"healthy"'; then
            log_info "Health check PASSED: Service is healthy (HTTP ${HTTP_CODE})."
            echo "${HTTP_BODY}"
            exit 0
        else
            log_warn "Endpoint returned HTTP 200, but payload indicates non-healthy status."
        fi
    else
        log_warn "Health check FAILED on attempt ${attempt}: HTTP status code was ${HTTP_CODE}."
    fi

    if [ "${attempt}" -lt "${MAX_RETRIES}" ]; then
        log_info "Waiting ${RETRY_INTERVAL}s before retry..."
        sleep "${RETRY_INTERVAL}"
    fi

    attempt=$((attempt + 1))
done

log_error "CRITICAL: Service health check failed after ${MAX_RETRIES} attempts against ${TARGET_URL}."
exit 1
