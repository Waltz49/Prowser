"""Log LM Studio / Gradio API calls to Tools > Debug > View log (stdout print log)."""

from __future__ import annotations

import inspect
import json
import traceback
from datetime import datetime
from functools import wraps
from typing import Any, Callable


def relax_json_for_log(json_string: str) -> str:
    """Decode JSON string escapes in quoted segments for more human-readable logs."""
    output_chars = []
    str_len = len(json_string)
    index = 0
    inside_string = False

    escape_sequences = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
    }

    while index < str_len:
        char = json_string[index]
        if not inside_string:
            if char == '"':
                inside_string = True
            output_chars.append(char)
            index += 1
        else:
            if char == "\\" and index + 1 < str_len:
                esc_char = json_string[index + 1]
                if esc_char in escape_sequences:
                    output_chars.append(escape_sequences[esc_char])
                    index += 2
                elif esc_char == "u" and index + 5 < str_len:
                    hex_digits = json_string[index + 2 : index + 6]
                    try:
                        output_chars.append(chr(int(hex_digits, 16)))
                        index += 6
                    except ValueError:
                        output_chars.append(char)
                        index += 1
                else:
                    output_chars.append(char)
                    index += 1
            elif char == '"':
                inside_string = False
                output_chars.append(char)
                index += 1
            else:
                output_chars.append(char)
                index += 1
    return "".join(output_chars)


def _write_log_line(text: str) -> None:
    print(text, end="" if text.endswith("\n") else "\n", flush=True)


def log_exception(exc: BaseException, *, exc_tb: Any | None = None) -> None:
    """Write a formatted exception block to the View log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exc_type = type(exc)

    parts = [
        f"\n{'=' * 50}",
        f"Timestamp: {timestamp}",
        f"Exception Type: {exc_type.__name__}",
        f"Exception Message: {exc}",
        "Traceback:",
    ]

    if exc_tb is None:
        if exc.__traceback__ is not None:
            parts.append("".join(traceback.format_tb(exc.__traceback__)).rstrip("\n"))
        else:
            parts.append("".join(traceback.format_exc()).rstrip("\n"))
    elif isinstance(exc_tb, str):
        parts.append(exc_tb.rstrip("\n"))
    else:
        parts.append("".join(traceback.format_tb(exc_tb)).rstrip("\n"))

    parts.append(f"{'=' * 50}\n")
    _write_log_line("\n".join(parts))


def print_call(func: Callable, wrap: bool = True) -> Callable:
    """
    Log function calls (lmstudio/gradio) to the View log.
    Only the call type and formatted params are logged; results are not logged.
    """
    def get_original_func(f):
        current = f
        try:
            while True:
                if hasattr(current, "__wrapped__"):
                    current = current.__wrapped__
                elif hasattr(current, "func"):
                    current = current.func
                elif hasattr(current, "__closure__") and current.__closure__:
                    for cell in current.__closure__:
                        if callable(cell.cell_contents):
                            current = cell.cell_contents
                            break
                else:
                    break
        except Exception:
            return f
        return current

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        original_func = get_original_func(func)

        if hasattr(original_func, "__self__"):
            class_name = original_func.__self__.__class__.__name__
            func_name = f"{class_name}.{original_func.__name__}"
        else:
            func_name = original_func.__name__

        sig = inspect.signature(func)
        bound_args = sig.bind_partial(*args, **kwargs)
        bound_args.apply_defaults()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = dict(bound_args.arguments) if hasattr(bound_args, "arguments") else {}
        payload.update(kwargs)

        def _serialize(obj):
            if hasattr(obj, "__class__") and "handle" in str(type(obj).__name__).lower():
                return f"<file_handle:{type(obj).__name__}>"
            if isinstance(obj, dict):
                return {k: _serialize(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_serialize(v) for v in obj]
            return obj

        is_gradio_predict = original_func.__name__ == "predict" and "api_name" in payload

        try:
            if is_gradio_predict:
                log_payload = {k: _serialize(v) for k, v in payload.items() if k != "self"}
                call_str = relax_json_for_log(
                    json.dumps(log_payload, indent=2, ensure_ascii=False, default=str)
                )
            else:
                safe_payload = _serialize(payload)
                call_str = relax_json_for_log(
                    json.dumps(safe_payload, indent=2, ensure_ascii=False, default=str)
                )
        except Exception:
            call_str = relax_json_for_log(
                json.dumps(
                    {"func": func_name, "error": "serialization failed"},
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

        call_type = func_name
        if "api_name" in payload:
            call_type = f"{func_name} {payload.get('api_name', '')}"
        _write_log_line(f"\n[{timestamp}] {call_type}\n{call_str}\n")

        return func(*args, **kwargs)

    if wrap:
        return wrapper
    return func
