# main.py
import asyncio
import logging
import time

import streamlit as st

from order_assistant import OrderAssistant

log_level = logging.INFO
log_format = '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'

root_logger = logging.getLogger()
root_logger.setLevel(log_level)

handler_exists = any(
    isinstance(h, logging.StreamHandler) and h.formatter and h.formatter._fmt == log_format
    for h in root_logger.handlers
)

if not handler_exists:
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    formatter = logging.Formatter(log_format)
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.info("Root logger configured with StreamHandler.")

for logger_name in ['autogen_core.events', 'httpx', 'httpcore']:
    noisy_logger = logging.getLogger(logger_name)
    noisy_logger.setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

API_BASE_URL = st.secrets.get("endpoints_url", "http://127.0.0.1:5001")
OPENAI_MODEL = st.secrets.get("openai_model", "gpt-4o-mini")
API_KEY = st.secrets.get("openai_api_key", "key")
if not API_KEY or API_KEY == "key":
    st.error("OpenAI API key is missing or is placeholder 'key'.")
    st.stop()

# Initialize Assistant
if 'order_assistant' not in st.session_state:
    st.session_state.order_assistant = OrderAssistant(api_key=API_KEY,
                                                      api_base_url=API_BASE_URL,
                                                      model=OPENAI_MODEL)

# indicates approval requests from a user
if 'pending_confirmation_details' not in st.session_state:
    st.session_state.pending_confirmation_details = None

if "messages" not in st.session_state:
    st.session_state.messages = []
    logger.info("Initialized 'messages' list in session state.")

# Main App Logic
st.title("🛒 Order Processing Assistant")

# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Confirmation Button Logic ---
if st.session_state.pending_confirmation_details:
    details = st.session_state.pending_confirmation_details['details']
    action_type = st.session_state.pending_confirmation_details['action_type']
    order_id = details.get('order_id', None)
    item_name = details.get('item_name', None)

    if order_id is None or item_name is None:
        # Clear pending state and rerun regardless of outcome
        st.session_state.pending_confirmation_details = None
        st.error('There was an issue while displaying confirmation')
        time.sleep(2)
        st.rerun()


    st.warning(f"⚠️ Please confirm you want to proceed with '{action_type}' for order #{order_id} ({item_name}).")

    if st.button(f'✅ Yes, Confirm {action_type.replace("_", " ").title()}',
                 key=f"confirm_{action_type}_{order_id}", type="primary"):
        logger.info(f"Confirmation button clicked for action '{action_type}', order '{order_id}'")
        assistant = st.session_state.order_assistant
        result_message = "Error: Confirmation details missing." # Default

        # Run the async execution function using asyncio.run
        try:
            result_message = asyncio.run(
                assistant.execute_confirmed_action(action_type=action_type, details=details)
            )
            logger.info(f"Confirmed action result: {result_message}")
            # Display result immediately
            if "✅" in result_message:
                st.success(result_message)
            elif "❌" in result_message or "Error" in result_message :
                 st.error(result_message)
            else: # Neutral message
                 st.info(result_message)

        except Exception as e:
            logger.error(f"Error executing confirmed action via asyncio.run: {e}", exc_info=True)
            result_message = f"An error occurred during confirmation: {e}"
            st.error(result_message)

        # Clear pending state and rerun regardless of outcome
        st.session_state.pending_confirmation_details = None
        logger.info("Cleared pending confirmation details.")


# --- Chat Input and Processing ---
if prompt := st.chat_input("Ask about orders (e.g., 'list orders', 'add pizza', 'cancel order ORD123')"):
    # Add user message to chat history and display it
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get assistant instance
    assistant = st.session_state.order_assistant

    # Display thinking indicator and process query
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("Thinking...")
        response_data = None
        try:
            # Run the async processing function using asyncio.run
            response_data = asyncio.run(assistant.process_user_query(query=prompt))
            assistant_reply_content = response_data['response_text']

            # Update placeholder and history
            message_placeholder.markdown(assistant_reply_content)
            st.session_state.messages.append({"role": "assistant", "content": assistant_reply_content})

            # Check if confirmation is now needed
            if response_data.get('confirmation_request'):
                logger.info("Assistant requires confirmation, storing details and rerunning.")
                st.session_state.pending_confirmation_details = response_data['confirmation_request']
                # Don't sleep here, rerun immediately to show button
                st.rerun()

        except Exception as e:
            logger.error(f"Error processing user query via asyncio.run: {e}", exc_info=True)
            error_reply = f"Sorry, an error occurred: {e}"
            message_placeholder.markdown(error_reply)
            st.session_state.messages.append({"role": "assistant", "content": error_reply})
