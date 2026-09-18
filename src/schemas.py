from __future__ import annotations

import datetime
from enum import Enum
from typing import Dict, Type
from pydantic import BaseModel, Field, field_validator


class TemperatureUnit(str, Enum):
    """Supported temperature units for weather lookup."""
    CELSIUS = "C"
    FAHRENHEIT = "F"


# ==============================================================================
# 1. FlightSearch Schemas
# ==============================================================================

class FlightSearch(BaseModel):
    """Input parameters for searching commercial flights."""
    origin: str = Field(..., min_length=2, description="Departure airport code or city name (e.g. 'JFK', 'MIA')")
    destination: str = Field(..., min_length=2, description="Arrival airport code or city name (e.g. 'LHR', 'DEL')")
    date: str = Field(..., description="Flight date in ISO-8601 format (YYYY-MM-DD)")

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("date must be a string in YYYY-MM-DD format")
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"date '{value}' is not a valid ISO-8601 date string (expected YYYY-MM-DD)")
        return value


class FlightSearchOutput(BaseModel):
    """Validated output structure returned by FlightSearch."""
    status: str = Field(default="success")
    flight_number: str
    origin: str
    destination: str
    date: str
    price: float


# Alias for explicit naming clarity
FlightSearchInput = FlightSearch


# ==============================================================================
# 2. CalendarBooking Schemas
# ==============================================================================

class CalendarBooking(BaseModel):
    """Input parameters for scheduling a calendar event."""
    event_title: str = Field(..., min_length=1, description="Title or subject of the meeting/event")
    start_time: datetime.datetime = Field(..., description="Event start timestamp in ISO format")
    duration_minutes: int = Field(..., gt=0, description="Duration of the event in minutes")


class CalendarBookingOutput(BaseModel):
    """Validated output structure returned by CalendarBooking."""
    status: str = Field(default="confirmed")
    booking_id: str
    event_title: str
    start_time: str
    duration_minutes: int


# Alias for explicit naming clarity
CalendarBookingInput = CalendarBooking


# ==============================================================================
# 3. WeatherLookup Schemas
# ==============================================================================

class WeatherLookup(BaseModel):
    """Input parameters for retrieving real-time weather information."""
    location: str = Field(..., min_length=1, description="Target city or location name (e.g. 'Tokyo', 'London')")
    unit: TemperatureUnit = Field(default=TemperatureUnit.CELSIUS, description="Temperature measurement unit ('C' or 'F')")


class WeatherLookupOutput(BaseModel):
    """Validated output structure returned by WeatherLookup."""
    status: str = Field(default="success")
    location: str
    temperature: float
    unit: str
    condition: str


# Alias for explicit naming clarity
WeatherLookupInput = WeatherLookup


# ==============================================================================
# 4. UnitConversion Schemas
# ==============================================================================

class UnitConversion(BaseModel):
    """Input parameters for converting values between physical units."""
    value: float = Field(..., description="Numeric magnitude to convert")
    from_unit: str = Field(..., min_length=1, description="Source unit (e.g. 'km', 'kg', 'miles')")
    to_unit: str = Field(..., min_length=1, description="Target unit to convert into")


class UnitConversionOutput(BaseModel):
    """Validated output structure returned by UnitConversion."""
    status: str = Field(default="success")
    original_value: float
    converted_value: float
    from_unit: str
    to_unit: str


# Alias for explicit naming clarity
UnitConversionInput = UnitConversion


# ==============================================================================
# Registry Mapping
# ==============================================================================

TOOL_INPUT_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "FlightSearch": FlightSearch,
    "CalendarBooking": CalendarBooking,
    "WeatherLookup": WeatherLookup,
    "UnitConversion": UnitConversion,
}

TOOL_OUTPUT_SCHEMAS: Dict[str, Type[BaseModel]] = {
    "FlightSearch": FlightSearchOutput,
    "CalendarBooking": CalendarBookingOutput,
    "WeatherLookup": WeatherLookupOutput,
    "UnitConversion": UnitConversionOutput,
}
