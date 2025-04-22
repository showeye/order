# tests/conftest.py

import datetime
import logging
import os
import subprocess
import sys
import time

import pytest
import tomllib
import requests
from pythonjsonlogger import jsonlogger

fixture_logger = logging.getLogger(__name__ + ".fixtures")
secrets_logger = logging.getLogger(__name__ + ".secrets")

@pytest.fixture(scope="session")
def secrets_config():
    """
    Loads configuration from order/.streamlit/secrets.toml.
    Returns a dictionary with the secrets.
    """
    # Assuming pytest runs from the parent directory of 'order/'
    secrets_file_path = os.path.join("order", ".streamlit", "secrets.toml")
    config = {}

    secrets_logger.info(f"Attempting to load secrets from: {secrets_file_path}")

    try:
        with open(secrets_file_path, "rb") as f:
            config = tomllib.load(f)
        secrets_logger.info("Secrets loaded successfully.")
        if "openai_api_key" not in config or "openai_model" not in config:
             secrets_logger.warning("Secrets file loaded, but 'openai_api_key' or 'openai_model' key might be missing.")

    except FileNotFoundError:
        secrets_logger.error(f"Secrets file not found at {secrets_file_path}. Real LLM tests will be skipped.")
    except tomllib.TOMLDecodeError as e:
        secrets_logger.error(f"Error decoding TOML file {secrets_file_path}: {e}")
        pytest.fail(f"Failed to parse secrets.toml: {e}")
    except Exception as e:
         secrets_logger.error(f"An unexpected error occurred loading secrets: {e}")
         pytest.fail(f"Unexpected error loading secrets.toml: {e}")

    return config


@pytest.fixture(scope="session")
def mock_api(request):
    """
    Starts the Flask mock API server (endpoints.py) in a subprocess
    for the test session, yields its base URL, and ensures teardown.
    """
    host = "127.0.0.1"
    port = 5001 # Should match the port in endpoints.py
    base_url = f"http://{host}:{port}"
    # Assuming pytest is run from the parent directory containing 'order/'
    api_script_path = os.path.join("order", "endpoints.py")

    if not os.path.exists(api_script_path):
         pytest.fail(f"Mock API script not found at: {api_script_path}. "
                     f"Current working directory: {os.getcwd()}")

    fixture_logger.info(f"Starting mock API server: {api_script_path} on {base_url}")

    # Redirect stdout/stderr to DEVNULL to avoid cluttering test output,
    try:
        process = subprocess.Popen(
            [sys.executable, api_script_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
         pytest.fail(f"Failed to start mock API subprocess: {e}")


    # --- Wait for the server to be ready ---
    max_wait_time = 15 # seconds
    start_time = time.time()
    server_ready = False
    while time.time() - start_time < max_wait_time:
        try:
            # Try to connect to a known endpoint (e.g., /list)
            response = requests.get(f"{base_url}/list", timeout=1)
            if response.status_code == 200:
                server_ready = True
                fixture_logger.info("Mock API server is ready.")
                break
        except requests.exceptions.ConnectionError:
            time.sleep(0.5) # Wait before retrying
        except requests.exceptions.RequestException as e:
            fixture_logger.warning(f"Error checking mock API status: {e}")
            time.sleep(0.5)

    if not server_ready:
        process.terminate() # Clean up the process if it started but didn't respond
        pytest.fail(f"Mock API server ({base_url}) did not become ready within {max_wait_time} seconds.")

    # --- Teardown function ---
    def finalize():
        fixture_logger.info(f"Tearing down mock API server (PID: {process.pid})...")
        process.terminate() # Send SIGTERM
        try:
            process.wait(timeout=5) # Wait for graceful shutdown
            fixture_logger.info("Mock API server terminated gracefully.")
        except subprocess.TimeoutExpired:
            fixture_logger.warning("Mock API server did not terminate gracefully, sending SIGKILL.")
            process.kill() # Force kill if termination fails

    request.addfinalizer(finalize) # Register teardown

    yield base_url

@pytest.fixture(scope="session", autouse=True)
def setup_logging(request):
    """
    Configures logging for the test session:
    - Clears existing root handlers.
    - Adds a FileHandler to write JSON logs to tests/logs/.
    - Optionally adds a StreamHandler for console output.
    """
    log_dir = "order/tests/logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f"evaluation_{timestamp}.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Prevents duplicate logs if modules also configure logging or pytest adds handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close()

    log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"
    json_format = "%(asctime)s %(levelname)s %(name)s %(message)s %(test_case_id)s %(event)s %(function)s %(f_args)s %(f_kwargs)s %(return_value)s %(exception)s %(duration_ms)s"

    formatter = jsonlogger.JsonFormatter(
        json_format,
        rename_fields={"levelname": "level", "asctime": "timestamp"},
        datefmt='%Y-%m-%dT%H:%M:%S.%fZ',
        json_ensure_ascii=False
    )

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    root_logger.info(f"Logging configured. JSON logs going to: {log_file}")

    yield

    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)
