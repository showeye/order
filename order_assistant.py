# order_assistant.py

import json
import logging
import datetime
from typing import List, Any, Optional

import httpx
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ChatCompletionClient

from tests.test_utils import logme_eval

logger = logging.getLogger(__name__)


class OrderAssistant:
    """Encapsulates the order management agent and its interaction logic."""

    def __init__(self,
                 api_key: str,
                 api_base_url: str,
                 model: str,
                 model_client: ChatCompletionClient | None = None, ):
        self.api_base_url = api_base_url
        self.model = model
        self._http_client = httpx.AsyncClient(base_url=api_base_url, timeout=10.0)
        self._model_client = model_client or OpenAIChatCompletionClient(model=self.model, api_key=api_key)

        # Internal state for feedback loop and confirmation flow
        self._last_action_result: Optional[str] = None
        self._pending_confirmation_details: Optional[dict] = None

        # Define the agent
        self._agent = AssistantAgent(
            name="OrderAssistantLogic",
            model_client=self._model_client,
            tools=[
                self._tool_track_order,
                self._tool_add_order,
                self._tool_cancel_order_check, # Tool to check eligibility
                self._tool_list_orders
            ],
            system_message="""You are a helpful assistant for managing orders via an API. 
            Use the available tools to add, track, list, or check cancellation eligibility for orders. 
            To cancel an order, first use the 'cancel_order_check' tool. 
            This tool checks if the order exists and gathers details. If the tool indicates the order might 
            be eligible for cancellation (by returning eligibility info), inform the user clearly
            that they must confirm the cancellation using a button in the interface. 
            Do NOT proceed with cancellation yourself. An order can be cancelled even if delivered.
            Always check with 'cancel_order_check' tool.
            
            There is only one tool available per round. If you list orders first, you have to respond 
            to the user first ASKING TO PROCEED. before being able to call another tool, say, 'cancel_order_check'."
            
            The system will handle the confirmation step externally. 
            If the tool indicates the order cannot be cancelled (e.g., not found, already cancelled),
             inform the user. If a system note appears detailing the result of a previous action, 
             acknowledge it if relevant.
             
             Only only order can be cancelled at the time.""",
            reflect_on_tool_use=True
        )
        logger.info("OrderAssistant initialized.")

    async def close(self):
        """Closes the underlying HTTP client."""
        await self._http_client.aclose()
        logger.info("OrderAssistant HTTP client closed.")

    # --- Tool Methods (Internal) ---
    # These methods are registered as tools with the AssistantAgent

    @logme_eval
    async def _tool_add_order(self, name: str, comment: Optional[str] = None) -> str:
        """API Call: Orders an item based on provided name and optional comment."""
        payload = {"item_name": name}
        if comment:
            payload["comment"] = comment
        response = await self._http_client.post("/add", json=payload)
        response.raise_for_status() # Let @logme_eval handle HTTPStatusError
        data = response.json()
        if data.get("success"):
            order_id = data.get("order_id", "unknown ID")
            return f"Order for '{name}' received! Order ID: {order_id}. Message: {data.get('message', '')}"
        else:
            return f"Failed to add order for '{name}'. Reason: {data.get('error', 'Unknown API error')}"

    @logme_eval
    async def _tool_cancel_order_check(self, order_id: str) -> dict[str, Any]:
        """API Call: Checks if an order exists and is potentially eligible for cancellation,
           considering a 10-day policy limit. Does NOT cancel. Returns details for the agent
           and potentially sets internal state if confirmation is needed.
        """
        response_payload = {'order_id': order_id, 'eligible_for_confirmation': False, 'comment': '', 'details': None}
        self._pending_confirmation_details = None  # Clear previous pending state

        try:
            # Check order existence and status via /track endpoint
            track_response = await self._http_client.get(f"/track/{order_id}")

            if track_response.status_code == 404:
                response_payload['comment'] = f"Order ID '{order_id}' not found."
                return response_payload

            track_response.raise_for_status()  # Handle other HTTP errors
            track_data = track_response.json()

            current_status = track_data.get('status', 'Unknown Status')
            item_name = track_data.get('item', 'Unknown Item')
            # Assume API returns placed_date as an ISO string
            placed_date_str = track_data.get('placed_date')

            order_details = {
                'order_id': order_id,
                'item_name': item_name,
                'current_status': current_status,
                'placed_date_str': placed_date_str  # Keep string for details if needed
            }
            response_payload['details'] = order_details

            # --- Policy Check Logic ---
            if current_status.lower() == 'cancelled':
                response_payload['eligible_for_confirmation'] = False
                response_payload['comment'] = f"Order {order_id} ({item_name}) has already been cancelled."
            elif placed_date_str:
                try:
                    # Parse the date string from API (assuming ISO format)
                    # Using fromisoformat which handles common ISO formats
                    placed_date_dt = datetime.datetime.fromisoformat(placed_date_str)

                    # Make comparison timezone-naive for simplicity,
                    # TODO: use timezone-aware datetimes
                    cutoff_date_limit = (datetime.datetime.now() - datetime.timedelta(days=10)).date()

                    if placed_date_dt.date() >= cutoff_date_limit:
                        # Within policy limit and not cancelled -> Eligible for confirmation
                        response_payload['eligible_for_confirmation'] = True
                        response_payload['comment'] = (
                            f"Order {order_id} ({item_name}, placed {placed_date_dt.date()}) "
                            f"status is '{current_status}'. "
                            "It is within the 10-day cancellation policy. "
                            "Inform the user confirmation is required via the UI button to attempt cancellation."
                        )
                        # Set internal state for process_user_query
                        self._pending_confirmation_details = {'action_type': 'cancel_order', 'details': order_details}
                        logger.info(f"Order {order_id} marked internally as pending confirmation (within policy).")
                    else:
                        # Outside policy limit
                        response_payload['eligible_for_confirmation'] = False
                        response_payload['comment'] = (
                            f"Order {order_id} ({item_name}, placed {placed_date_dt.date()}) cannot be cancelled. "
                            f"It is older than the 10-day policy limit (cutoff date: {cutoff_date_limit})."
                        )
                        logger.warning(f"Order {order_id} ineligible for cancellation due to policy age.")

                except ValueError:
                    # Handle error parsing the date string from API
                    response_payload['eligible_for_confirmation'] = False
                    response_payload[
                        'comment'] = (f"Could not verify cancellation policy for order {order_id}. Invalid date format "
                                      f"received from API.")
                    logger.error(f"Failed to parse placed_date_str '{placed_date_str}' for order {order_id}")
            else:
                # Placed date missing from API response
                response_payload['eligible_for_confirmation'] = False
                response_payload[
                    'comment'] = (f"Could not verify cancellation policy for order {order_id}. Placement date missing "
                                  f"from API response.")
                logger.warning(f"Missing placed_date in API response for order {order_id}")


        except httpx.HTTPStatusError as e:
            # Error handled by @logme_eval, but we set a comment here
            response_payload[
                'comment'] = (f"API error checking order {order_id} status ({e.response.status_code}). "
                              f"Cannot determine eligibility.")
        except Exception as e:
            # Error handled by @logme_eval, set comment
            response_payload[
                'comment'] = f"An unexpected error occurred checking order {order_id}. Cannot determine eligibility."
            # Ensure pending state is clear on unexpected error
            self._pending_confirmation_details = None

        return response_payload

    @logme_eval
    async def _tool_track_order(self, order_id: str) -> str:
        """API Call: Gets tracking information for an order."""
        response = await self._http_client.get(f"/track/{order_id}")
        # Handle 404 specifically for a cleaner message
        if response.status_code == 404:
            return f"Order ID '{order_id}' not found."
        response.raise_for_status() # Let @logme_eval handle other errors
        data = response.json()
        if data.get("success"):
            # Return the detailed message from the API
            return data.get("detail", f"Status for order {order_id}: {data.get('status', 'Unknown')}")
        else:
            return f"Could not track order {order_id}. Reason: {data.get('error', 'Unknown API error')}"

    @logme_eval
    async def _tool_list_orders(self) -> dict | str:
        """API Call: Lists all available orders."""
        response = await self._http_client.get("/list")
        response.raise_for_status() # Let @logme_eval handle errors
        data = response.json()
        if data.get("success"):
            orders_data = data.get("orders", {})
            if not orders_data:
                return {"message": "There are currently no orders."}
            return orders_data # Return the dictionary of orders
        else:
            return f"Failed to list orders. Reason: {data.get('error', 'Unknown API error')}"

    # --- Public Methods for UI Interaction ---

    @logme_eval
    async def process_user_query(self, query: str) -> dict:
        """Processes a user query using the agent and returns response + confirmation needs."""
        logger.info(f"Processing query: '{query}'")
        messages_to_agent: List[TextMessage] = []

        # Inject result from last confirmed action if available
        if self._last_action_result:
            system_note = f"System Note: The outcome of the last confirmed action was: {self._last_action_result}"
            messages_to_agent.append(TextMessage(content=system_note, source="system"))
            logger.info(f"Injecting system note: {system_note}")
            self._last_action_result = None # Clear after injecting

        messages_to_agent.append(TextMessage(content=query, source="user"))

        # Clear pending confirmation before agent run, it will be set by tool if needed
        self._pending_confirmation_details = None

        # Run the agent
        cancellation_token = CancellationToken()
        agent_response = await self._agent.on_messages(messages_to_agent, cancellation_token=cancellation_token)

        response_text = "Sorry, I encountered an issue." # Default
        if hasattr(agent_response, 'chat_message') and agent_response.chat_message:
            response_text = agent_response.chat_message.content

        # Check if the cancel_order_check tool set the internal pending state
        confirmation_request = self._pending_confirmation_details
        if confirmation_request:
             logger.info(f"Agent run resulted in pending confirmation: {confirmation_request}")
             # Clear internal state now that we're passing it to UI
             self._pending_confirmation_details = None

        return {
            "response_text": response_text,
            "confirmation_request": confirmation_request # This will be None if tool didn't set it
        }

    @logme_eval
    async def execute_confirmed_action(self, action_type: str, details: dict) -> str:
        """Executes an action after UI confirmation (e.g., calls cancel API)."""
        result_message = f"Unknown action type: {action_type}"
        self._last_action_result = None # Clear previous result before new action

        if action_type == 'cancel_order':
            order_id = details.get('order_id')
            item_name = details.get('item_name', 'Unknown Item')
            if not order_id:
                result_message = "Error: Missing order_id for cancellation."
                logger.error(result_message)
            else:
                logger.info(f"Executing confirmed cancellation for order: {order_id}")
                try:
                    # Make the actual cancellation API call
                    response = await self._http_client.post(f"/cancel/{order_id}")

                    # Process response based on status code and content
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("success"):
                            result_message = f"✅ Order #{order_id} ({item_name}) cancelled successfully."
                        else:
                            # Should ideally have non-200 status, but handle just in case
                            result_message = (f"❌ API reported failure for order #{order_id}: "
                                              f"{data.get('error', 'Unknown reason')}")
                    elif response.status_code == 403: # Forbidden - Policy failure
                        data = response.json()
                        result_message = (f"❌ Cannot cancel order #{order_id} ({item_name}). "
                                          f"Reason: {data.get('error', 'Policy restriction')}")
                    elif response.status_code == 404: # Not Found
                        result_message = f"❌ Failed to cancel order #{order_id}. Reason: Order not found by API."
                    else:
                        # Raise other 4xx/5xx errors to be caught below
                        response.raise_for_status()

                except httpx.HTTPStatusError as e:
                    # Logged by @logme_eval, format message here
                    try: error_data = e.response.json(); detail = error_data.get('error', e.response.text)
                    except json.JSONDecodeError: detail = e.response.text
                    result_message = (f"❌ Failed to cancel order #{order_id}. "
                                      f"API Error ({e.response.status_code}): {detail}")
                except httpx.RequestError as e:
                    # Logged by @logme_eval, format message here
                    result_message = f"❌ Failed to cancel order #{order_id}: Could not connect to the order service."
                except Exception as e:
                    # Logged by @logme_eval, format message here
                    result_message = f"❌ An unexpected error occurred trying to cancel order #{order_id}."

                logger.info(f"Cancellation result for {order_id}: {result_message}")
        else:
             logger.warning(f"Attempted to execute unhandled confirmed action type: {action_type}")

        # Store result for feedback loop
        self._last_action_result = result_message
        return result_message