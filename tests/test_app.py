"""
Unit and integration tests for the Disaster Recovery Health Status Service
and the Flask Food Ordering Application.
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

# Ensure repo root and src are on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as flask_app
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
    """HTTP endpoint integration tests for DR health service (src/app.py)."""

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


class TestFlaskFoodOrderingApp(unittest.TestCase):
    """Unit tests for the Flask Food Ordering application (app.py)."""

    def setUp(self):
        flask_app.app.config["TESTING"] = True
        self.client = flask_app.app.test_client()

        # Isolate orders file in a temporary folder
        self.test_dir = tempfile.mkdtemp()
        self.temp_orders_file = os.path.join(self.test_dir, "orders.json")
        self.orig_orders_file = flask_app.ORDERS_FILE
        flask_app.ORDERS_FILE = self.temp_orders_file

    def tearDown(self):
        flask_app.ORDERS_FILE = self.orig_orders_file
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_home_page_renders_successfully(self):
        """Verifies GET / renders index.html with 200 OK."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.data.decode("utf-8")
        self.assertIn("Food Order", content)

    def test_order_creation_success(self):
        """Verifies POST /order saves the order and renders success page."""
        form_data = {
            "name": "Sarah Connor",
            "mobile": "5551234567",
            "food": "Pepperoni Pizza",
            "quantity": "2"
        }
        response = self.client.post("/order", data=form_data)
        self.assertEqual(response.status_code, 200)

        # Check HTML response
        content = response.data.decode("utf-8")
        self.assertIn("Order Successful", content)
        self.assertIn("Sarah Connor", content)

        # Check JSON persistence
        self.assertTrue(os.path.exists(self.temp_orders_file))
        with open(self.temp_orders_file, "r", encoding="utf-8") as file:
            saved_orders = json.load(file)

        self.assertEqual(len(saved_orders), 1)
        self.assertEqual(saved_orders[0]["name"], "Sarah Connor")
        self.assertEqual(saved_orders[0]["food"], "Pepperoni Pizza")
        self.assertEqual(saved_orders[0]["quantity"], "2")
        self.assertIn("date", saved_orders[0])

    def test_multiple_orders_accumulate(self):
        """Verifies subsequent orders append to existing orders list."""
        self.client.post("/order", data={"name": "User 1", "mobile": "111", "food": "Pasta", "quantity": "1"})
        self.client.post("/order", data={"name": "User 2", "mobile": "222", "food": "Salad", "quantity": "3"})

        with open(self.temp_orders_file, "r", encoding="utf-8") as file:
            saved_orders = json.load(file)

        self.assertEqual(len(saved_orders), 2)
        self.assertEqual(saved_orders[0]["name"], "User 1")
        self.assertEqual(saved_orders[1]["name"], "User 2")


if __name__ == "__main__":
    unittest.main()
