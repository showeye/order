# tests/test_utils.py

import logging
import time
import functools
import contextvars
import json
import traceback
from typing import Any, Callable

# Context variable to hold the current test case ID
test_id_var = contextvars.ContextVar('test_id', default=None)

eval_logger = logging.getLogger("evaluation")
eval_logger.setLevel(logging.DEBUG)

MAX_REPR_LEN = 200 # Max length for string representations in logs

def _safe_serialize(obj: Any) -> Any:
    """Attempts to serialize an object for JSON logging, falling back to repr()."""
    try:
        json.dumps(obj)
        return obj
    except (TypeError, OverflowError):
        try:
            representation = repr(obj)
            if len(representation) > MAX_REPR_LEN:
                representation = representation[:MAX_REPR_LEN] + '...'
            return representation
        except Exception:
            return "<SerializationError>"

def logme_eval(func: Callable) -> Callable:
    """
    Decorator for async functions to log entry, exit, duration, args, kwargs,
    return value/exception, and contextvars like test_id in JSON format.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        log_prefix = f"{func.__module__}.{func.__qualname__}"
        test_case_id = test_id_var.get()

        serializable_args = [_safe_serialize(arg) for arg in args]
        serializable_kwargs = {k: _safe_serialize(v) for k, v in kwargs.items()}

        entry_details = {
            "test_case_id": test_case_id,
            "event": "entry",
            "function": log_prefix,
            "f_args": serializable_args,
            "f_kwargs": serializable_kwargs,
        }

        logger = logging.getLogger(func.__module__)
        logger.info(f"Calling {log_prefix}", extra=entry_details)

        result = None
        exception_info = None
        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            exception_info = {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(limit=3),
            }
            raise
        finally:
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000

            exit_details = {
                "test_case_id": test_case_id,
                "event": "exit",
                "function": log_prefix,
                "duration_ms": round(duration_ms, 2),
            }
            log_message = f"Finished {log_prefix}"

            if exception_info:
                exit_details["exception"] = exception_info
                log_message += f" with error: {exception_info['type']}"
                logger.error(log_message, extra=exit_details, exc_info=False)
            else:
                exit_details["return_value"] = _safe_serialize(result)
                logger.info(log_message, extra=exit_details)

    return wrapper