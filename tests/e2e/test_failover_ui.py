"""
Automated smoke test suite using Python and Selenium for post-failover
verification.

Verifies:
1. Active secondary recovery endpoint responds with HTTP 200 OK.
2. Headless Chrome UI rendering and page title verification.
3. Health status indicator element visibility and operational state.
4. Post-failover interactive UI capability (menu elements, navigation, form).
"""

import glob
import json
import os
import sys
import threading
import time
import urllib.request
import pytest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from werkzeug.serving import make_server

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as flask_app  # noqa: E402

_CACHED_DRIVER_PATH = None


class EphemeralServerThread(threading.Thread):
    """Runs Flask application in background thread on ephemeral port."""

    def __init__(self, wsgi_app, host="127.0.0.1", port=0):
        super().__init__()
        self.server = make_server(host, port, wsgi_app)
        self.port = self.server.port
        self.url = f"http://{host}:{self.port}"
        self.daemon = True

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def get_headless_chrome_options():
    """Configures ChromeOptions for headless execution as specified."""
    options = Options()
    # Explicit required headless flags
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # Additional stability options for Windows and CI environments
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    return options


def get_chromedriver_path():
    """Resolves and caches chromedriver binary path via webdriver-manager."""
    global _CACHED_DRIVER_PATH
    if _CACHED_DRIVER_PATH and os.path.exists(_CACHED_DRIVER_PATH):
        return _CACHED_DRIVER_PATH

    try:
        _CACHED_DRIVER_PATH = ChromeDriverManager().install()
        if _CACHED_DRIVER_PATH and os.path.exists(_CACHED_DRIVER_PATH):
            return _CACHED_DRIVER_PATH
    except Exception:
        pass

    # Search local webdriver-manager cache folder
    wdm_glob = os.path.expanduser(
        os.path.join("~", ".wdm", "drivers", "chromedriver", "**", "*.exe")
    )
    candidates = glob.glob(wdm_glob, recursive=True)
    if candidates:
        _CACHED_DRIVER_PATH = candidates[-1]
        return _CACHED_DRIVER_PATH

    return None


def init_chrome_driver():
    """Initializes Selenium Chrome WebDriver using webdriver-manager."""
    options = get_headless_chrome_options()
    driver_path = get_chromedriver_path()
    if driver_path and os.path.exists(driver_path):
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        # Fallback to Selenium 4 built-in automated driver manager
        driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(30)
    driver.implicitly_wait(10)
    return driver


@pytest.fixture(scope="session")
def active_secondary_endpoint():
    """
    Provides the active secondary recovery endpoint URL.
    Uses SECONDARY_ENDPOINT or APP_URL if specified in the environment;
    otherwise launches an ephemeral instance in active secondary mode.
    """
    env_endpoint = (
        os.environ.get("SECONDARY_ENDPOINT") or os.environ.get("APP_URL")
    )
    if env_endpoint:
        yield env_endpoint.rstrip("/")
        return

    # Set secondary disaster recovery environment context
    orig_region = os.environ.get("APP_REGION")
    orig_role = os.environ.get("APP_ROLE")
    os.environ["APP_REGION"] = "secondary-us-west-2"
    os.environ["APP_ROLE"] = "secondary-active"

    flask_app.app.config["TESTING"] = True
    flask_app.is_healthy = True

    server = EphemeralServerThread(flask_app.app)
    server.start()
    time.sleep(0.2)

    yield server.url

    server.shutdown()
    server.join(timeout=3)

    # Restore original environment variables
    if orig_region is not None:
        os.environ["APP_REGION"] = orig_region
    else:
        os.environ.pop("APP_REGION", None)

    if orig_role is not None:
        os.environ["APP_ROLE"] = orig_role
    else:
        os.environ.pop("APP_ROLE", None)


@pytest.fixture(scope="session")
def chrome_driver():
    """Session-scoped fixture providing headless Chrome browser instance."""
    driver = init_chrome_driver()
    yield driver
    try:
        driver.quit()
    except Exception:
        pass


def test_secondary_recovery_endpoint_http_200(active_secondary_endpoint):
    """
    Verifies that the active secondary recovery endpoint responds with
    HTTP 200 OK on both the web route (/) and health check (/health).
    """
    # 1. Verify HTTP 200 response on base UI endpoint
    req_root = urllib.request.Request(
        f"{active_secondary_endpoint}/",
        headers={"User-Agent": "PostFailoverSmokeTester/1.0"}
    )
    with urllib.request.urlopen(req_root, timeout=5) as resp_root:
        assert resp_root.status == 200, (
            f"Expected HTTP 200 for root, got {resp_root.status}"
        )

    # 2. Verify HTTP 200 response on health recovery endpoint
    req_health = urllib.request.Request(
        f"{active_secondary_endpoint}/health",
        headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(req_health, timeout=5) as resp_health:
        assert resp_health.status == 200, (
            f"Expected HTTP 200 for health endpoint, got {resp_health.status}"
        )
        body = json.loads(resp_health.read().decode("utf-8"))
        assert body.get("status") == "UP", (
            f"Expected UP status in health payload, got {body.get('status')}"
        )
        assert "uptime_seconds" in body, (
            "Health payload missing uptime_seconds"
        )


def test_post_failover_ui_page_title(chrome_driver, active_secondary_endpoint):
    """
    Verifies web page title of active secondary recovery endpoint
    using headless Chrome.
    """
    chrome_driver.get(active_secondary_endpoint)

    # Wait for page title to be present
    WebDriverWait(chrome_driver, 10).until(
        EC.title_contains("Foodie Hub")
    )

    page_title = chrome_driver.title
    assert "Foodie Hub" in page_title, (
        f"Unexpected page title: '{page_title}'"
    )
    assert "Online Food Ordering" in page_title, (
        f"Missing food ordering subtitle in: '{page_title}'"
    )
    assert page_title == "Foodie Hub - Online Food Ordering"


def test_post_failover_ui_health_status_indicator(
    chrome_driver, active_secondary_endpoint
):
    """
    Verifies health status indicator on active secondary recovery UI:
    - Indicator is present and visible in DOM.
    - Displays operational / healthy secondary status.
    - Correct data attribute reflecting healthy state.
    """
    chrome_driver.get(active_secondary_endpoint)

    # Wait for the health status indicator element to be visible
    indicator = WebDriverWait(chrome_driver, 10).until(
        EC.visibility_of_element_located((By.ID, "health-status-indicator"))
    )
    assert indicator.is_displayed(), "Health status indicator is not visible"

    indicator_text = indicator.text
    assert (
        "Operational" in indicator_text
    ), (
        f"Health indicator did not display operational status: "
        f"'{indicator_text}'"
    )

    # Verify status data attribute
    status_attr = indicator.get_attribute("data-status")
    assert status_attr == "UP", (
        f"Expected data-status 'UP', got '{status_attr}'"
    )

    # Verify nested badge element
    badge = indicator.find_element(By.ID, "health-status-badge")
    assert badge.is_displayed(), "Health status badge span is not visible"
    assert "System Status" in badge.text, (
        f"Unexpected badge text: '{badge.text}'"
    )


def test_post_failover_ui_full_smoke_verification(
    chrome_driver, active_secondary_endpoint
):
    """
    Comprehensive smoke test validating:
    - HTTP 200 response on active secondary endpoint.
    - Page title verification.
    - Health status indicator verification.
    - Presence of interactive navigation and order form post-failover.
    """
    # 1. Load active secondary endpoint
    chrome_driver.get(active_secondary_endpoint)

    # 2. Page title assertion
    assert chrome_driver.title == "Foodie Hub - Online Food Ordering"

    # 3. Health status indicator assertion
    indicator = chrome_driver.find_element(By.ID, "health-status-indicator")
    assert indicator.is_displayed()
    assert "Operational (Active Secondary)" in indicator.text

    # 4. Verify primary UI navigation links are present and displayed
    for nav_text in ["Home", "Menu", "Order"]:
        nav_link = chrome_driver.find_element(By.LINK_TEXT, nav_text)
        assert nav_link.is_displayed(), (
            f"Navigation link '{nav_text}' is missing"
        )

    # 5. Verify menu section cards are rendered
    menu_section = chrome_driver.find_element(By.ID, "menu")
    assert menu_section.is_displayed(), "Menu section is not displayed"
    food_cards = chrome_driver.find_elements(By.CLASS_NAME, "food-card")
    assert len(food_cards) >= 4, (
        f"Expected at least 4 food cards, found {len(food_cards)}"
    )

    # 6. Verify order section and form inputs are present and enabled
    order_form = chrome_driver.find_element(By.TAG_NAME, "form")
    assert order_form.is_displayed(), "Order form is not displayed"

    name_input = chrome_driver.find_element(By.ID, "name")
    mobile_input = chrome_driver.find_element(By.ID, "mobile")
    food_select = chrome_driver.find_element(By.ID, "food")
    quantity_input = chrome_driver.find_element(By.ID, "quantity")
    submit_btn = order_form.find_element(By.TAG_NAME, "button")

    assert name_input.is_enabled()
    assert mobile_input.is_enabled()
    assert food_select.is_enabled()
    assert quantity_input.is_enabled()
    assert submit_btn.is_enabled()
    assert submit_btn.text == "Place Order"


if __name__ == "__main__":
    sys.exit(pytest.main(["-v", __file__]))
