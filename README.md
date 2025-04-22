# Order Management Assistant

This project provides a Streamlit-based web application interface to interact with an AI-powered Order Assistant. The assistant uses tools to communicate with a mock order management API for tasks like adding, tracking, listing, and cancelling orders.

## Features

* **Order Tracking:** Get the status of existing orders.
* **Order Placement:** Add new items to the order system.
* **Order Listing:** View all current orders and their details.
* **Order Cancellation:** Check eligibility and request cancellation for recent orders (within a 10-day policy), requiring user confirmation via the UI.
* **AI Assistant:** Leverages an LLM (like GPT-4o-mini) via AutoGen to understand user requests and interact with the mock API.
* **Mock API:** A Flask-based server (`endpoints.py`) simulates a real order management backend.
* **Testing Suite:** Includes `pytest` tests (`test_cases.py`) to verify agent behavior against ground truth (`ground_truth.json`), along with log analysis capabilities (`analyze_logs.py`).

## Prerequisites

* Python 3.x
* `pip` for installing packages

## Installation

1.  **Clone the repository (if applicable) or ensure you have the `order` folder.**
2.  **Navigate to the project directory:**
    ```bash
    cd path/to/order_folder
    ```
3.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
4.  **Install required libraries:**
    ```bash
    pip install -r requirements.txt
    ```
    *(See `requirements.txt` for a full list of dependencies)*

## Configuration

1.  **Secrets:** The application requires API keys and model configuration. These should be stored in `order/.streamlit/secrets.toml`. Create this file if it doesn't exist.
    * **Required:** `openai_api_key` and `openai_model`.
    * **Optional:** `endpoints_url` (defaults to `http://127.0.0.1:5001` if not specified).

    Example `secrets.toml`:
    ```toml
    openai_api_key = "YOUR_OPENAI_API_KEY"
    openai_model = "gpt-4o-mini" # Or your preferred model
    # endpoints_url = "[http://127.0.0.1:5001](http://127.0.0.1:5001)" # Optional override
    ```

## Running the Application

1.  **Start the Mock API Server:** Open a terminal, navigate to the `order` directory, and run:
    ```bash
    python endpoints.py
    ```
    This will start the Flask server, typically on `http://127.0.0.1:5001`. Keep this running in the background.

2.  **Run the Streamlit UI:** Open another terminal, navigate to the `order` directory (and ensure your virtual environment is active), then run:
    ```bash
    streamlit run main.py
    ```
    This will launch the Streamlit application in your web browser. You can interact with the Order Assistant through the chat interface.

## Running Tests

The project uses `pytest` for testing the agent's logic and tool usage against predefined scenarios.

1.  **Ensure the Mock API is running** (as described in the "Running the Application" section).
2.  **Navigate to the parent directory of `order`**.
3.  **Run pytest:**
    ```bash
    pytest order/tests/test_cases.py
    ```
    Test logs (in JSON format) will be generated in the `order/tests/logs/` directory.

## Log Analysis

After running tests, you can analyze the generated JSON logs to calculate metrics like tool selection accuracy, parameter extraction accuracy, and success rates.

1.  **Navigate to the parent directory of `order`**.
2.  **Run the analysis script:**
    ```bash
    python order/tests/analyze_logs.py [path/to/log_file.log]
    ```
    * If you omit the log file path, the script will attempt to find and analyze the latest `evaluation_*.log` file in `order/tests/logs/`.
    * Analysis reports (text summary and CSV data) will be saved in the `order/tests/reports/` directory.

## Project Structure

```
order/
├── .streamlit/
│   └── secrets.toml        # API keys and configuration (Needs to be created)
├── tests/
│   ├── logs/               # Test execution logs (JSON format)
│   ├── reports/            # Log analysis reports (txt, csv)
│   ├── analyze_logs.py     # Script to analyze test logs
│   ├── conftest.py         # Pytest configuration and fixtures
│   ├── ground_truth.json   # Expected outcomes for test cases
│   ├── test_api.py         # Basic API endpoint tests (optional standalone run)
│   ├── test_cases.py       # Pytest test scenarios for the assistant
│   └── test_utils.py       # Utility functions for testing (e.g., logging decorator)
├── endpoints.py            # Flask Mock API server implementation
├── main.py                 # Main Streamlit application script
├── order_assistant.py      # Core logic for the Order Assistant Agent and tool definitions
├── README.md               # This file
└── requirements.txt        # Python package dependencies
