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


class FaultContext:
    """Thread-safe and process-configurable context for deterministic fault injection."""
    current_fault: str = "NONE"
    timeout_delay_seconds: float = 0.05

    @classmethod
    def set_fault(cls, fault: str) -> None:
        cls.current_fault = fault.upper() if fault else "NONE"

    @classmethod
    def reset(cls) -> None:
        cls.current_fault = "NONE"


def inject_fault(func: Callable[..., Dict[str, Any]]) -> Callable[..., Dict[str, Any]]:
    """
    Decorator intercepting mock tool invocations to induce deterministic faults.
    Supports directives:
      - NONE: Normal pass-through execution.
      - TIMEOUT: Simulates upstream latency and raises TimeoutError.
      - MALFORMED / MALFORMED_RESPONSE: Executes tool but alters the returned payload
        so it violates the Pydantic output schema.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        fault = FaultContext.current_fault.upper()

        if fault == FaultType.TIMEOUT.value:
            if FaultContext.timeout_delay_seconds > 0:
                time.sleep(FaultContext.timeout_delay_seconds)
            raise TimeoutError(f"Upstream service for {func.__name__} timed out (HTTP 504 / Connection Timeout)")

        result = func(*args, **kwargs)

        if fault in (FaultType.MALFORMED.value, FaultType.MALFORMED_RESPONSE.value):
            # Deliberately alter the dictionary to violate the expected Pydantic output schema
            return {
                "msg": "legacy_ok",
                "raw_result": str(result),
                "unparsed_text": "Vendor response shape deprecated: fields missing or renamed"
            }

        return result

    return wrapper


# Alias to satisfy both singular and plural naming conventions
inject_faults = inject_fault
