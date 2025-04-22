# endpoints.py
import datetime
import logging
from flask import Flask, jsonify, request

app = Flask(__name__)

log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger(__name__)

# --- In-Memory Order Storage ---

now = datetime.datetime.now()
ten_days_ago = now - datetime.timedelta(days=10)
eleven_days_ago = now - datetime.timedelta(days=11)

orders = {
    "ORD123": {
        "id": "ORD123",
        "item": "Running Shoes",
        "status": "Shipped",
        "placed_date": (datetime.datetime.now() - datetime.timedelta(days=5)),
        "comment": "Customer requested fast delivery."
    },
    "ORD456": {
        "id": "ORD456",
        "item": "Laptop Stand",
        "status": "Processing",
        "placed_date": (datetime.datetime.now() - datetime.timedelta(days=15)),
        "comment": "Awaiting stock."
    },
    "ORD789": {
        "id": "ORD789",
        "item": "Coffee Mug",
        "status": "Delivered",
        "placed_date": (datetime.datetime.now() - datetime.timedelta(days=2)),
        "comment": "Gift wrapped."
    },
    "ORD910": {
        "id": "ORD910",
        "item": "Boundary Case 10d",
        "status": "Processing",
        "placed_date": ten_days_ago,  # Exactly 10 days old
        "comment": "Test 10-day boundary."
    },
    "ORD911": {
        "id": "ORD911",
        "item": "Boundary Case 11d",
        "status": "Processing",
        "placed_date": eleven_days_ago,  # Exactly 11 days old
        "comment": "Test 11-day boundary (ineligible)."
    },
    "ORD912": {
        "id": "ORD912",
        "item": "Standard Mug",
        "status": "Cancelled",
        "placed_date": (now - datetime.timedelta(days=4)), # Placed recently, but already cancelled
        "comment": "Order previously cancelled by support."
    }
}
# Keep track of the last used numeric ID part
last_order_num = 912

# --- Helper Function for New Order ID ---
def generate_new_order_id():
    """Generates a new sequential order ID like ORDXXX."""
    global last_order_num
    last_order_num += 1
    return f"ORD{last_order_num}"

# --- API Endpoints ---

@app.route('/track/<string:order_id>', methods=['GET'])
def track_order_endpoint(order_id):
    """Tracks the status of a specific order."""
    logger.info(f"Track request received for order ID: {order_id}")
    order = orders.get(order_id)
    if order:
        logger.info(f"Order {order_id} found. Status: {order['status']}")
        # Include item and comment in the response detail for completeness
        detail_message = (
            f"Order {order_id} ({order.get('item', 'Unknown Item')}) "
            f"is currently {order['status']}. "
            f"Comment: {order.get('comment', 'N/A')}"
        )
        return jsonify({
            "success": True,
            "order_id": order_id,
            "status": order["status"],
            "item": order.get("item"), # Return item name
            "placed_date": order.get("placed_date").isoformat(),
            "comment": order.get("comment"), # Return comment
            "detail": detail_message
        })
    else:
        logger.warning(f"Order {order_id} not found for tracking.")
        return jsonify({
            "success": False,
            "order_id": order_id,
            "error": "Order not found"
        }), 404

@app.route('/cancel/<string:order_id>', methods=['POST'])
def cancel_order_endpoint(order_id):
    """Attempts to cancel an order based on policy (e.g., placed date)."""
    logger.info(f"Cancel request received for order ID: {order_id}")
    order = orders.get(order_id)
    if not order:
        logger.warning(f"Order {order_id} not found for cancellation.")
        return jsonify({
            "success": False,
            "order_id": order_id,
            "error": "Order not found"
        }), 404

    # Example Policy: Cannot cancel if order is older than 10 days
    cancellation_cutoff = datetime.datetime.now() - datetime.timedelta(days=10)

    if order["status"].lower() == 'cancelled':
        logger.info(f"Order {order_id} is already cancelled.")
        return jsonify({
            "success": True,
            "order_id": order_id,
            "message": "Order was already cancelled."
        }), 409

    if "placed_date" not in order:
         logger.warning(f"Order {order_id} cannot be cancelled, missing placement date.")
         return jsonify({
              "success": False,
              "order_id": order_id,
              "error": f"Order cannot be cancelled (missing placement date)."
         }), 403 # Or 400 Bad Request

    if order["placed_date"] > cancellation_cutoff:
        order["status"] = "Cancelled"
        order["comment"] = order.get("comment", "") + " [User Cancelled]"
        orders[order_id] = order # Update state
        logger.info(f"Order {order_id} cancelled successfully.")
        return jsonify({
            "success": True,
            "order_id": order_id,
            "message": "Order cancelled successfully."
        })
    else:
        logger.warning(f"Order {order_id} cannot be cancelled due to policy (too old).")
        return jsonify({
            "success": False,
            "order_id": order_id,
            "error": f"Order cannot be cancelled (placed on {order['placed_date'].date()}). Policy limit: 10 days."
        }), 403 # Using 403 Forbidden as it's a policy restriction

@app.route('/add', methods=['POST'])
def add_order_endpoint():
    """Adds a new order."""
    logger.info("Add order request received.")
    if not request.is_json:
        logger.error("Add order request failed: Request body is not JSON.")
        return jsonify({"success": False, "error": "Request must be JSON"}), 400

    data = request.get_json()
    item_name = data.get('item_name')
    user_comment = data.get('comment', 'Order placed.')

    if not item_name:
        logger.error("Add order request failed: 'item_name' is missing.")
        return jsonify({"success": False, "error": "Missing 'item_name' in request body"}), 400

    new_id = generate_new_order_id()
    new_order = {
        "id": new_id,
        "item": item_name,
        "status": "Processing", # Default status for new orders
        "placed_date": datetime.datetime.now(),
        "comment": user_comment
    }
    orders[new_id] = new_order
    logger.info(f"New order added successfully: ID {new_id}, Item: {item_name}")

    return jsonify({
        "success": True,
        "order_id": new_id,
        "message": f"Order for '{item_name}' added successfully with ID {new_id}."
    }), 201 # 201 Created status code

@app.route('/list', methods=['GET'])
def list_orders_endpoint():
    """Lists all current orders."""
    logger.info("List orders request received.")
    return jsonify({
        "success": True,
        "orders": orders
    })

# --- Run Flask App ---
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5001, debug=True)
