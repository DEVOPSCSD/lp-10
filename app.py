from flask import Flask, render_template, request, jsonify, Response
import os
import json
import time
from datetime import datetime

app = Flask(__name__)

START_TIME = time.time()
is_healthy = True

os.makedirs("data", exist_ok=True)
ORDERS_FILE = "data/orders.json"

@app.route("/")
def home():
    return render_template("index.html")

# JSON Health check endpoint
@app.route("/health", methods=["GET"])
def health():
    if is_healthy:
        return jsonify({
            "status": "UP",
            "uptime_seconds": round(time.time() - START_TIME, 2),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200
    return jsonify({
        "status": "DOWN",
        "error": "Service marked unhealthy"
    }), 503

# Prometheus Scrape endpoint (Plain text format)
@app.route("/metrics", methods=["GET"])
def metrics():
    app_status_val = 1 if is_healthy else 0
    uptime = round(time.time() - START_TIME, 2)
    
    metrics_data = (
        f"# HELP app_health_status Application health status (1 = UP, 0 = DOWN)\n"
        f"# TYPE app_health_status gauge\n"
        f"app_health_status {app_status_val}\n\n"
        f"# HELP app_uptime_seconds Total application uptime in seconds\n"
        f"# TYPE app_uptime_seconds counter\n"
        f"app_uptime_seconds {uptime}\n"
    )
    return Response(metrics_data, mimetype="text/plain; version=0.0.4")

@app.route("/simulate-failure", methods=["POST"])
def simulate_failure():
    global is_healthy
    is_healthy = False
    return jsonify({"status": "Failure simulated", "is_healthy": False}), 200

@app.route("/simulate-recover", methods=["POST"])
def simulate_recover():
    global is_healthy
    is_healthy = True
    return jsonify({"status": "Recovery simulated", "is_healthy": True}), 200

@app.route("/order", methods=["POST"])
def order():
    name = request.form.get("name")
    mobile = request.form.get("mobile")
    food = request.form.get("food")
    quantity = request.form.get("quantity")

    order_data = {
        "name": name,
        "mobile": mobile,
        "food": food,
        "quantity": quantity,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, "r") as file:
            orders = json.load(file)
    else:
        orders = []

    orders.append(order_data)

    with open(ORDERS_FILE, "w") as file:
        json.dump(orders, file, indent=4)

    return render_template("success.html", order=order_data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
