from flask import Flask, render_template, request
import os
import json
from datetime import datetime

app = Flask(__name__)

# Create data folder if it doesn't exist
os.makedirs("data", exist_ok=True)

ORDERS_FILE = "data/orders.json"


# Home page
@app.route("/")
def home():
    return render_template("index.html")


# Handle food orders
@app.route("/order", methods=["POST"])
def order():
    name = request.form.get("name")
    mobile = request.form.get("mobile")
    food = request.form.get("food")
    quantity = request.form.get("quantity")

    # Create order details
    order_data = {
        "name": name,
        "mobile": mobile,
        "food": food,
        "quantity": quantity,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Read existing orders
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, "r") as file:
            orders = json.load(file)
    else:
        orders = []

    # Add new order
    orders.append(order_data)

    # Save orders
    with open(ORDERS_FILE, "w") as file:
        json.dump(orders, file, indent=4)

    return render_template("success.html", order=order_data)


# Run the application
if __name__ == "__main__":
    app.run(debug=True)