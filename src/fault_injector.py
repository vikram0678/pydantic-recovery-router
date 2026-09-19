from __future__ import annotations

import functools
import time
from enum import Enum
from typing import Any, Callable, Dict


class FaultType(str, Enum):
    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    MALFORMED = "MALFORMED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    PERSISTENT_TIMEOUT = "PERSISTENT_TIMEOUT"


class FaultContext:
    """Configurable context for injected upstream failures."""
    current_fault: str = "NONE"
    timeout_delay: float = 0.01
    transient: bool = True
    call_count: int = 0

    @classmethod
    def set_fault(cls, fault: str, transient: bool = True) -> None:
        cls.current_fault = str(fault).upper() if fault else "NONE"
        cls.transient = transient
        cls.call_count = 0

    @classmethod
    def reset(cls) -> None:
        cls.current_fault = "NONE"
        cls.transient = True
        cls.call_count = 0

    @classmethod
    def set_timeout_delay(cls, seconds: float) -> None:
        cls.timeout_delay = seconds

    @classmethod
    def get_timeout_delay(cls) -> float:
        return cls.timeout_delay

    @classmethod
    def increment_call_count(cls) -> int:
        cls.call_count += 1
        return cls.call_count

    @classmethod
    def is_transient(cls) -> bool:
        return cls.transient


def _corrupt_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Alters returned payload keys to simulate API schema changes."""
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
    corrupted["vendor_schema_version"] = "v0-legacy"
    return corrupted


def inject_fault(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    """Decorator to intercept tool calls and induce deterministic faults."""
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        fault = str(FaultContext.current_fault).upper()
        call_count = FaultContext.increment_call_count()
        is_transient = FaultContext.is_transient()

        if fault == FaultType.PERSISTENT_TIMEOUT.value or (fault == FaultType.TIMEOUT.value and (not is_transient or call_count == 1)):
            delay = FaultContext.get_timeout_delay()
            if delay > 0:
                time.sleep(delay)
            raise TimeoutError("Upstream service timed out")

        result = func(*args, **kwargs)

        if fault in (FaultType.MALFORMED.value, FaultType.MALFORMED_RESPONSE.value):
            if not is_transient or call_count == 1:
                return _corrupt_payload(result)

        return result

    return wrapper


inject_faults = inject_fault
