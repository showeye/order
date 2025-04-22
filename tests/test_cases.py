# order/tests/test_cases.py

import asyncio

import pytest
import httpx

from order_assistant import OrderAssistant
from tests.test_utils import test_id_var


def _has_secrets(config):
    """Checks if necessary secrets were loaded by the fixture."""
    return config and config.get("openai_api_key") and config.get("openai_model")

requires_secrets = pytest.mark.skipif(
"not _has_secrets(config)",
    reason="Requires secrets (openai_api_key, openai_model) to be loaded from order/.streamlit/secrets.toml"
)

@pytest.fixture
async def configured_assistant(mock_api, secrets_config, request):
    if not _has_secrets(secrets_config):
         pytest.skip("Secrets not found, skipping assistant creation.")

    api_key = secrets_config.get("openai_api_key")
    model_id = secrets_config.get("openai_model")

    assistant = OrderAssistant(
        api_key=api_key,
        api_base_url=mock_api,
        model=model_id
    )

    async def async_cleanup():
        await assistant.close()

    request.addfinalizer(lambda: asyncio.run(async_cleanup()))

    return assistant


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_existing_track_order(configured_assistant):
    """
    Scenario: User asks to track an existing, known order (e.g., ORD123).
    Expected: LLM selects _tool_track_order, passes correct order_id.
             Response indicates the known status (e.g., "Shipped").
    """

    ground_truth = {
        "test_id": "test_existing_track_order",
        "expected_tool": "_tool_track_order",
        "expected_params": {"order_id": "ORD123"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "What's the status for my order ORD123?"
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "ORD123" in response_data["response_text"]
    assert "shipped" in response_data["response_text"].lower()
    assert response_data.get("confirmation_request") is None
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_nonexistent_track_order(configured_assistant):
    """
    Scenario: User asks to track an order ID that does not exist (e.g., ORD999).
    Expected: LLM selects _tool_track_order, passes correct order_id.
             Tool returns "Order not found" message from the mock API.
             Agent relays this information to the user.
    """

    ground_truth = {
        "test_id": "test_nonexistent_track_order",
        "expected_tool": "_tool_track_order",
        "expected_params": {"order_id": "ORD999"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "Can you track order ORD999 for me?"
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "ORD999" in response_data["response_text"]
    # cannot be found
    assert ("not found" in response_data["response_text"].lower()
            or "couldn't find" in response_data["response_text"].lower()
            or "cannot be found" in response_data["response_text"].lower())
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_add_order_basic(configured_assistant):
    """
    Scenario: User asks to add a new item.
    Expected: LLM selects _tool_add_order, passes item name.
             Response confirms the order was added and includes a new ID.
    """

    ground_truth = {
        "test_id": "test_add_order_basic",
        "expected_tool": "_tool_add_order",
        "expected_params": {"name": "Deluxe Pizza"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "Please add a 'Deluxe Pizza' to my orders."
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "Deluxe Pizza" in response_data["response_text"]
    assert "added" in response_data["response_text"].lower()
    assert "successfully" in response_data["response_text"].lower()
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_list_orders(configured_assistant):
    """
    Scenario: User asks to list all current orders.
    Expected: LLM selects _tool_list_orders.
             Response presents the list of orders from the mock API.
    """

    ground_truth = {
        "test_id": "test_list_orders",
        "expected_tool": "_tool_list_orders",
        "expected_params": {},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "Show me all my orders."
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "ORD123" in response_data["response_text"]
    assert "Running Shoes" in response_data["response_text"]
    assert "ORD456" in response_data["response_text"]
    assert "Laptop Stand" in response_data["response_text"]
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)

@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_cancel_check_eligible_order(configured_assistant):
    """
    Scenario: User asks to cancel an order eligible for cancellation (e.g., ORD789, recent).
    Expected: LLM selects _tool_cancel_order_check, passes correct order_id.
             Tool determines eligibility based on mock API data & policy.
             Agent response *informs* the user confirmation is needed via UI.
             Response data includes 'confirmation_request' details.
    """
    ground_truth = {
        "test_id": "test_cancel_check_eligible_order",
        "expected_tool": "_tool_cancel_order_check",
        "expected_params": {"order_id": "ORD789"},
        "expected_confirmation_needed": True
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "I want to cancel order ORD789."
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "ORD789" in response_data["response_text"]
    assert "Coffee Mug" in response_data["response_text"]
    assert "confirm" in response_data["response_text"].lower()
    assert "button" in response_data["response_text"].lower()

    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]
    if ground_truth["expected_confirmation_needed"]:
        assert response_data["confirmation_request"]["action_type"] == "cancel_order"
        assert response_data["confirmation_request"]["details"]["order_id"] == "ORD789"

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_cancel_check_ineligible_order_policy(configured_assistant):
    """
    Scenario: User asks to cancel an order ineligible due to policy (e.g., ORD456, too old).
    Expected: LLM selects _tool_cancel_order_check, passes correct order_id.
             Tool determines ineligibility based on mock API data & policy.
             Agent response informs the user it *cannot* be cancelled due to policy.
             No confirmation request should be generated.
    """

    ground_truth = {
        "test_id": "test_cancel_check_ineligible_order_policy",
        "expected_tool": "_tool_cancel_order_check",
        "expected_params": {"order_id": "ORD456"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "Is it possible to cancel my order ORD456?"
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "ORD456" in response_data["response_text"]
    assert ("cannot be cancelled" in response_data["response_text"].lower()
            or "cannot cancel" in response_data["response_text"].lower())
    assert "policy" in response_data["response_text"].lower()
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_cancel_check_nonexistent_order(configured_assistant):
    """
    Scenario: User asks to cancel an order that doesn't exist (e.g., ORD000).
    Expected: LLM selects _tool_cancel_order_check, passes correct order_id.
             Tool determines ineligibility (order not found).
             Agent response informs the user the order was not found.
             No confirmation request should be generated.
    """

    ground_truth = {
        "test_id": "test_cancel_check_nonexistent_order",
        "expected_tool": "_tool_cancel_order_check",
        "expected_params": {"order_id": "ORD000"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    configured_assistant = await configured_assistant

    user_query = "Please cancel order ORD000."
    response_data = await configured_assistant.process_user_query(query=user_query)

    assert "ORD000" in response_data["response_text"]

    assert ("not found" in response_data["response_text"].lower()
            or "couldn't find" in response_data["response_text"].lower()
            or "cannot be found" in response_data["response_text"].lower())
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)

@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_cancel_check_boundary_10_days(configured_assistant):
    """
    Scenario: User asks to cancel an order exactly 10 days old (ORD910).
    Expected: LLM selects _tool_cancel_order_check.
             Tool determines eligibility (still within policy).
             Agent prompts for confirmation.
             Response data includes 'confirmation_request'.
    """

    configured_assistant = await configured_assistant

    ground_truth = {
        "test_id": "test_cancel_check_boundary_10_days",
        "expected_tool": "_tool_cancel_order_check",
        "expected_params": {"order_id": "ORD910"},
        "expected_confirmation_needed": True
    }
    token = test_id_var.set(ground_truth['test_id'])
    assistant = configured_assistant

    user_query = "Could you cancel order ORD910 please?"
    response_data = await assistant.process_user_query(query=user_query)

    assert "ORD910" in response_data["response_text"]
    assert "eligible for cancellation" in response_data["response_text"].lower()
    assert "confirm" in response_data["response_text"].lower()
    assert "button" in response_data["response_text"].lower()
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]
    if ground_truth["expected_confirmation_needed"]:
        assert response_data["confirmation_request"]["action_type"] == "cancel_order"
        assert response_data["confirmation_request"]["details"]["order_id"] == "ORD910"

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_cancel_check_boundary_11_days(configured_assistant):
    """
    Scenario: User asks to cancel an order exactly 11 days old (ORD911).
    Expected: LLM selects _tool_cancel_order_check.
             Tool determines ineligibility (just outside policy).
             Agent informs user it cannot be cancelled due to policy.
             No 'confirmation_request' should be generated.
    """

    configured_assistant = await configured_assistant

    ground_truth = {
        "test_id": "test_cancel_check_boundary_11_days",
        "expected_tool": "_tool_cancel_order_check",
        "expected_params": {"order_id": "ORD911"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])
    assistant = configured_assistant

    user_query = "I need to cancel ORD911."
    response_data = await assistant.process_user_query(query=user_query)

    assert "ORD911" in response_data["response_text"]
    assert ("cannot be cancelled" in response_data["response_text"].lower()
            or "cannot cancel" in response_data["response_text"].lower())
    assert "policy" in response_data["response_text"].lower()
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]

    test_id_var.reset(token)

@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_cancel_check_cancelled_ORD912(configured_assistant):
    """
    Scenario: User asks to cancel an order that is already cancelled (ORD912).
    Expected: LLM selects _tool_cancel_order_check.
             Tool finds order is already cancelled.
             Agent response informs user it's already cancelled.
             No confirmation request.
    """

    ground_truth = {
        "test_id": "test_cancel_check_cancelled_ORD912",
        "expected_tool": "_tool_cancel_order_check",
        "expected_params": {"order_id": "ORD912"},
        "expected_confirmation_needed": False
    }
    token = test_id_var.set(ground_truth['test_id'])

    assistant = await configured_assistant

    user_query = "Try cancelling order ORD912 again."
    response_data = await assistant.process_user_query(query=user_query)

    assert "ORD912" in response_data["response_text"]
    assert "already been cancelled" in response_data["response_text"].lower()
    assert (response_data.get("confirmation_request") is not None) == ground_truth["expected_confirmation_needed"]
    assert response_data.get("confirmation_request") is None

    test_id_var.reset(token)


@pytest.mark.asyncio
@pytest.mark.usefixtures("secrets_config")
async def test_network_fault_track_order(configured_assistant, monkeypatch):
    """
    Scenario: User asks to track an order, but the API call to /track times out.
    Expected: LLM selects _tool_track_order.
             Tool call log shows exception (tool_call_succeeded = False).
             Agent response contains an apology and suggests retrying.
    """

    ground_truth = {
        "test_id": "test_network_fault_track_order",
        "expected_tool": "_tool_track_order",
        "expected_params": {"order_id": "ORD123"},
        "expected_confirmation_needed": False,
        "expected_tool_call_succeeded": False,
        "expected_response_contains": ["sorry", "apology", "try again", "issue", "problem"]
    }
    token = test_id_var.set(ground_truth['test_id'])

    assistant = await configured_assistant

    # Monkeypatch httpx.AsyncClient.get
    original_get = httpx.AsyncClient.get

    async def mock_get(self, url, *args, **kwargs):
        if "/track/" in str(url):
            print(f"\n[MonkeyPatch] Intercepted GET {url}, raising TimeoutException")
            raise httpx.TimeoutException("Simulated network timeout on /track")

        # Raising an error for any unhandled GET
        raise NotImplementedError(f"Monkeypatched GET received unexpected URL: {url}")


    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    user_query = "Track my order ORD123 please."
    response_data = {}
    try:
        response_data = await assistant.process_user_query(query=user_query)
    finally:
        test_id_var.reset(token)

    response_text_lower = response_data.get("response_text", "").lower()
    assert any(keyword in response_text_lower for keyword in ground_truth["expected_response_contains"]), \
        f"Response '{response_text_lower}' did not contain expected keywords: {ground_truth['expected_response_contains']}"

    assert response_data.get("confirmation_request") is None, "Confirmation request should be None on tool failure"
