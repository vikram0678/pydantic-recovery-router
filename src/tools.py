from __future__ import annotations

import datetime
from typing import Any, Callable, Dict
from src.fault_injector import inject_faults


@inject_faults
def flight_search(origin: str, destination: str, date: str) -> Dict[str, Any]:
    """Mock flight search tool returning static flight booking details."""
    origin_clean = str(origin).strip().upper()
    dest_clean = str(destination).strip().upper()
    flight_code = f"FL-{abs(hash(f'{origin_clean}_{dest_clean}')) % 900 + 100}"
    
    return {
        "status": "success",
        "flight_number": flight_code,
        "origin": origin_clean,
        "destination": dest_clean,
        "date": str(date),
        "price": 389.50
    }


@inject_faults
def calendar_booking(event_title: str, start_time: Any, duration_minutes: int) -> Dict[str, Any]:
    """Mock calendar booking tool returning a reservation confirmation."""
    start_str = start_time.isoformat() if hasattr(start_time, "isoformat") else str(start_time)
    booking_id = f"CAL-{abs(hash(event_title + start_str)) % 90000 + 10000}"

    return {
        "status": "confirmed",
        "booking_id": booking_id,
        "event_title": str(event_title),
        "start_time": start_str,
        "duration_minutes": int(duration_minutes)
    }


@inject_faults
def weather_lookup(location: str, unit: str = "C") -> Dict[str, Any]:
    """Mock weather service returning regional forecast data."""
    unit_str = unit.value if hasattr(unit, "value") else str(unit).upper()
    base_temp = 22.0
    temp = base_temp if unit_str == "C" else (base_temp * 9 / 5) + 32

    return {
        "status": "success",
        "location": str(location).title(),
        "temperature": round(temp, 1),
        "unit": unit_str,
        "condition": "Partly Cloudy"
    }


@inject_faults
def unit_conversion(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    """Mock unit conversion service supporting standard distance, weight, and temperature metrics."""
    val = float(value)
    src = str(from_unit).lower().strip()
    dst = str(to_unit).lower().strip()

    # Deterministic conversion factors
    factors = {
        ("km", "miles"): 0.621371,
        ("miles", "km"): 1.60934,
        ("kg", "lbs"): 2.20462,
        ("lbs", "kg"): 0.453592,
        ("m", "ft"): 3.28084,
        ("ft", "m"): 0.3048,
        ("c", "f"): lambda v: (v * 9 / 5) + 32,
        ("f", "c"): lambda v: (v - 32) * 5 / 9,
    }

    key = (src, dst)
    if key in factors:
        converter = factors[key]
        converted = converter(val) if callable(converter) else val * converter
    else:
        # Default conversion approximation if arbitrary units
        converted = val * 1.0

    return {
        "status": "success",
        "original_value": val,
        "converted_value": round(converted, 2),
        "from_unit": src,
        "to_unit": dst
    }


TOOL_REGISTRY: Dict[str, Callable[..., Dict[str, Any]]] = {
    "FlightSearch": flight_search,
    "CalendarBooking": calendar_booking,
    "WeatherLookup": weather_lookup,
    "UnitConversion": unit_conversion,
}
