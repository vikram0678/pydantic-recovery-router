from __future__ import annotations

import datetime
import pytest
from pydantic import ValidationError

from src.schemas import (
    FlightSearch,
    FlightSearchOutput,
    CalendarBooking,
    CalendarBookingOutput,
    WeatherLookup,
    WeatherLookupOutput,
    UnitConversion,
    UnitConversionOutput,
    TemperatureUnit,
    TOOL_INPUT_SCHEMAS,
    TOOL_OUTPUT_SCHEMAS,
)
from src.fault_injector import FaultContext, FaultType
from src.tools import flight_search, calendar_booking, weather_lookup, unit_conversion


# ==============================================================================
# 1. Tests for Tool Input Schemas & Validation
# ==============================================================================

def test_flight_search_valid():
    """Verify FlightSearch instantiates with valid ISO date string."""
    model = FlightSearch(origin="JFK", destination="LHR", date="2026-10-15")
    assert model.origin == "JFK"
    assert model.destination == "LHR"
    assert model.date == "2026-10-15"


def test_flight_search_missing_and_invalid_date():
    """Verify FlightSearch raises ValidationError for missing fields and malformed dates."""
    # Missing date
    with pytest.raises(ValidationError) as exc_info:
        FlightSearch(origin="JFK", destination="LHR")
    assert any(err["loc"] == ("date",) for err in exc_info.value.errors())

    # Invalid date format like "tomorrow"
    with pytest.raises(ValidationError) as exc_info:
        FlightSearch(origin="JFK", destination="LHR", date="tomorrow")
    assert any("ISO-8601" in err["msg"] for err in exc_info.value.errors())


def test_calendar_booking_valid_and_invalid():
    """Verify CalendarBooking requires valid datetime and positive duration."""
    now = datetime.datetime.now(datetime.timezone.utc)
    model = CalendarBooking(event_title="Engineering Sync", start_time=now, duration_minutes=45)
    assert model.event_title == "Engineering Sync"
    assert model.duration_minutes == 45

    # Missing duration
    with pytest.raises(ValidationError):
        CalendarBooking(event_title="Sync", start_time=now)

    # Invalid duration type
    with pytest.raises(ValidationError):
        CalendarBooking(event_title="Sync", start_time=now, duration_minutes="not-an-int")


def test_weather_lookup_valid_and_invalid():
    """Verify WeatherLookup enforces location and Enum temperature unit."""
    model = WeatherLookup(location="Tokyo", unit=TemperatureUnit.CELSIUS)
    assert model.location == "Tokyo"
    assert model.unit == TemperatureUnit.CELSIUS

    # Invalid unit value
    with pytest.raises(ValidationError):
        WeatherLookup(location="Tokyo", unit="Kelvin")


def test_unit_conversion_valid_and_invalid():
    """Verify UnitConversion requires float value and unit strings."""
    model = UnitConversion(value=100.0, from_unit="km", to_unit="miles")
    assert model.value == 100.0
    assert model.from_unit == "km"

    # Missing value
    with pytest.raises(ValidationError):
        UnitConversion(from_unit="km", to_unit="miles")


def test_registry_has_all_four_tools():
    """Verify registry contains all 4 required tool schemas."""
    expected_tools = {"FlightSearch", "CalendarBooking", "WeatherLookup", "UnitConversion"}
    assert set(TOOL_INPUT_SCHEMAS.keys()) == expected_tools
    assert set(TOOL_OUTPUT_SCHEMAS.keys()) == expected_tools


# ==============================================================================
# 2. Tests for Fault Injection Middleware
# ==============================================================================

def test_fault_injector_none_pass_through():
    """Normal execution without faults passes output schema validation."""
    FaultContext.set_fault("NONE")
    result = flight_search(origin="JFK", destination="LHR", date="2026-10-15")
    
    # Must validate cleanly against output schema
    validated = FlightSearchOutput(**result)
    assert validated.status == "success"
    assert validated.origin == "JFK"


def test_fault_injector_timeout():
    """TIMEOUT fault induces a TimeoutError."""
    FaultContext.set_fault("TIMEOUT")
    with pytest.raises(TimeoutError) as exc_info:
        weather_lookup(location="Berlin", unit="C")
    assert "timed out" in str(exc_info.value).lower()
    FaultContext.reset()


def test_fault_injector_malformed_response_violates_output_schema():
    """MALFORMED_RESPONSE fault modifies output payload violating output schema."""
    FaultContext.set_fault("MALFORMED_RESPONSE")
    raw_payload = weather_lookup(location="Berlin", unit="C")
    
    # Raw payload should fail output schema validation
    with pytest.raises(ValidationError):
        WeatherLookupOutput(**raw_payload)
    FaultContext.reset()
