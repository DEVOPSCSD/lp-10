"""
Unit and integration tests for the Disaster Recovery Health Status Service.
"""

import json
import os
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

# Ensure src is in python path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.app import HealthRequestHandler, get_system_health


class TestHealthLogic(unittest.TestCase):
    """Tests for system health state resolution."""

    def setUp(self):
        # Save original environment
        self.original_env = os.environ.copy()
        os.environ["SUPPRESS_HTTP_LOGS"] = "true"

    def tearDown(self):
        # Restore environment
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_default_health_state(self):
        os.environ.pop("APP_REGION", None)
        os.environ.pop("APP_ROLE", None)
        os.environ.pop("DB_STATUS", None)
        os.environ.pop("MAINTENANCE_MODE", None)

        health = get_system_health()
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["region"], "primary-us-east-1")
        self.assertEqual(health["role"], "primary")
        self.assertEqual(health["database"], "connected")
        self.assertFalse(health["maintenance_mode"])
        self.assertIn("timestamp", health)

    def test_custom_region_and_role(self):
        os.environ["APP_REGION"] = "dr-us-west-2"
        os.environ["APP_ROLE"] = "standby"

        health = get_system_health()
        self.assertEqual(health["region"], "dr-us-west-2")
        self.assertEqual(health["role"], "standby")

    def test_unhealthy_when_database_disconnected(self):
        os.environ["DB_STATUS"] = "disconnected"

        health = get_system_health()
        self.assertEqual(health["status"], "unhealthy")
        self.assertEqual(health["database"], "disconnected")

    def test_unhealthy_when_in_maintenance_mode(self):
        os.environ["MAINTENANCE_MODE"] = "true"

        health = get_system_health()
        self.assertEqual(health["status"], "unhealthy")
        self.assertTrue(health["maintenance_mode"])


class TestHealthServiceHTTP(unittest.TestCase):
    """HTTP endpoint integration tests."""

    @classmethod
    def setUpClass(cls):
        os.environ["SUPPRESS_HTTP_LOGS"] = "true"
        # Bind to port 0 for dynamic ephemeral port allocation
        cls.server = HTTPServer(("127.0.0.1", 0), HealthRequestHandler)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever)
        cls.server_thread.daemon = True
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)

    def setUp(self):
        self.original_env = os.environ.copy()
        os.environ["SUPPRESS_HTTP_LOGS"] = "true"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_get_root_health_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/"
        with urlopen(url) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Type"), "application/json")
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")
            self.assertIn("service", data)

    def test_get_healthz_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/healthz"
        with urlopen(url) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["status"], "healthy")

    def test_get_livez_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/livez"
        with urlopen(url) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["status"], "alive")

    def test_get_readyz_healthy(self):
        url = f"http://127.0.0.1:{self.port}/readyz"
        with urlopen(url) as response:
            self.assertEqual(response.status, 200)
            data = json.loads(response.read().decode("utf-8"))
            self.assertEqual(data["status"], "ready")

    def test_get_readyz_unhealthy(self):
        os.environ["DB_STATUS"] = "disconnected"
        url = f"http://127.0.0.1:{self.port}/readyz"
        with self.assertRaises(HTTPError) as ctx:
            urlopen(url)
        self.assertEqual(ctx.exception.code, 503)
        ctx.exception.close()

    def test_get_metrics_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/metrics"
        with urlopen(url) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
            self.assertIn("app_health_status", body)
            self.assertIn("app_is_primary", body)

    def test_404_not_found(self):
        url = f"http://127.0.0.1:{self.port}/non-existent-endpoint"
        with self.assertRaises(HTTPError) as ctx:
            urlopen(url)
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
