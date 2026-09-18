from __future__ import annotations

import contextvars
import functools
import time
from enum import Enum
from typing import Any, Callable, Dict

_current_fault_var: contextvars.ContextVar[str] = contextvars.ContextVar("current_fault", default="NONE")
_timeout_delay_var: contextvars.ContextVar[float] = contextvars.ContextVar("timeout_delay", default=0.05)


class FaultType(str, Enum):
    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    MALFORMED = "MALFORMED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"


class FaultContext:
    """
    Thread-safe and process-configurable context for deterministic fault injection.
    Can be configured per-test-case or per-request to simulate upstream degradation.
    """
    _fallback_fault: str = "NONE"
    _fallback_delay: float = 0.05

    @classmethod
    @property
    def current_fault(cls) -> str:
        try:
            return _current_fault_var.get()
        except LookupError:
            return cls._fallback_fault

    @classmethod
    def set_fault(cls, fault: str) -> None:
        val = fault.upper() if fault else "NONE"
        cls._fallback_fault = val
        _current_fault_var.set(val)

    @classmethod
    def reset(cls) -> None:
        cls._fallback_fault = "NONE"
        _current_fault_var.set("NONE")

    @classmethod
    def set_timeout_delay(cls, seconds: float) -> None:
        cls._fallback_delay = seconds
        _timeout_delay_var.set(seconds)

    @classmethod
    def get_timeout_delay(cls) -> float:
        try:
            return _timeout_delay_var.get()
        except LookupError:
            return cls._fallback_delay


def _corrupt_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Alters returned payload keys to simulate real-world API drift/breaking changes
    (e.g., vendor renamed keys from {"status": "ok", "temperature": 72} to
    {"msg": "success", "temp_reading": "72 degrees"}).
    This deterministically triggers Pydantic output validation errors while
    preserving raw data for the Schema Repair recovery strategy.
    """
    key_renames = {
        "status": "msg",
        "flight_number": "flight_code",
        "origin": "departure_airport",
        "destination": "arrival_airport",
        "date": "flight_date_str",
        "price": "fare_amount",
        "event_title": "meeting_title",
        "start_time": "time_iso",
        "duration_minutes": "length_in_minutes",
        "booking_id": "reservation_id",
        "location": "city_name",
        "temperature": "temp_reading",
        "unit": "scale",
        "condition": "weather_desc",
        "original_value": "input_val",
        "converted_value": "output_val",
        "from_unit": "src_unit",
        "to_unit": "dst_unit",
    }
    
    corrupted: Dict[str, Any] = {}
    for key, value in data.items():
        corrupted[key_renames.get(key, f"raw_{key}")] = value
    corrupted["vendor_schema_version"] = "v0-legacy-unsupported"
    return corrupted


def inject_fault(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    """
    Decorator intercepting mock tool invocations to induce deterministic faults.
    Directives supported:
      - NONE: Normal pass-through execution.
      - TIMEOUT: Simulates upstream latency, then raises TimeoutError.
      - MALFORMED / MALFORMED_RESPONSE: Executes tool normally, then alters the
        returned dictionary so it violates the expected Pydantic output schema.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        fault = FaultContext.current_fault.upper()

        if fault == FaultType.TIMEOUT.value:
            delay = FaultContext.get_timeout_delay()
            if delay > 0:
                time.sleep(delay)
            raise TimeoutError(f"Upstream service for '{func.__name__}' timed out (HTTP 504 Gateway Timeout)")

        result = func(*args, **kwargs)

        if fault in (FaultType.MALFORMED.value, FaultType.MALFORMED_RESPONSE.value):
            return _corrupt_payload(result)

        return result

    return wrapper


# Plural alias for convenience and contract compliance
inject_faults = inject_fault

