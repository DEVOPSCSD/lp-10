"""
Health Status Service for DevOps-Based Disaster Recovery System.

Provides HTTP endpoints for health, readiness, and liveness monitoring,
along with disaster recovery status metadata.
"""

import json
import os
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


def get_system_health():
    """Generates health status dictionary based on environment and system state."""
    region = os.getenv("APP_REGION", "primary-us-east-1")
    role = os.getenv("APP_ROLE", "primary")  # 'primary' or 'standby'
    environment = os.getenv("APP_ENV", "production")
    version = os.getenv("APP_VERSION", "1.0.0")
    db_status = os.getenv("DB_STATUS", "connected")
    maintenance_mode = os.getenv("MAINTENANCE_MODE", "false").lower() == "true"

    is_healthy = db_status == "connected" and not maintenance_mode

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "service": "disaster-recovery-health-service",
        "version": version,
        "region": region,
        "role": role,
        "environment": environment,
        "database": db_status,
        "maintenance_mode": maintenance_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
    }


class HealthRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health and disaster recovery probes."""

    def _send_json_response(self, status_code, payload):
        response_bytes = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        health_data = get_system_health()

        if self.path in ("/", "/health", "/healthz"):
            status_code = 200 if health_data["status"] == "healthy" else 503
            self._send_json_response(status_code, health_data)
        elif self.path == "/livez":
            # Liveness probe
            self._send_json_response(
                200,
                {"status": "alive", "timestamp": health_data["timestamp"]},
            )
        elif self.path == "/readyz":
            # Readiness probe - checks DB connectivity and maintenance mode
            if health_data["status"] == "healthy":
                self._send_json_response(
                    200,
                    {
                        "status": "ready",
                        "region": health_data["region"],
                        "role": health_data["role"],
                    },
                )
            else:
                self._send_json_response(
                    503,
                    {
                        "status": "not_ready",
                        "reason": "database or maintenance condition",
                    },
                )
        elif self.path == "/metrics":
            # Prometheus plain text metrics
            is_healthy_val = 1 if health_data["status"] == "healthy" else 0
            is_primary_val = 1 if health_data["role"] == "primary" else 0
            metrics_lines = [
                "# HELP app_health_status Health status (1 = healthy, 0 = unhealthy)",
                "# TYPE app_health_status gauge",
                f'app_health_status{{region="{health_data["region"]}",role="{health_data["role"]}"}} {is_healthy_val}',
                "# HELP app_is_primary Primary status indicator (1 = primary, 0 = standby)",
                "# TYPE app_is_primary gauge",
                f'app_is_primary{{region="{health_data["region"]}"}} {is_primary_val}',
            ]
            response_bytes = "\n".join(metrics_lines).encode("utf-8") + b"\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)
        else:
            self._send_json_response(404, {"error": "Not Found", "path": self.path})

    def log_message(self, format, *args):
        # Override to suppress standard noisy logging or format cleanly
        if os.getenv("SUPPRESS_HTTP_LOGS", "false").lower() == "true":
            return
        sys.stderr.write(
            f"[{datetime.now(timezone.utc).isoformat()}] {self.address_string()} - {format % args}\n"
        )


def run_server(host="0.0.0.0", port=8080):
    server_address = (host, port)
    httpd = HTTPServer(server_address, HealthRequestHandler)
    print(f"Starting Disaster Recovery Health Service on {host}:{port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")
    run_server(host=host, port=port)
