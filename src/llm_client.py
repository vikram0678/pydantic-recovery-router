from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class LLMClient:
    """
    LLM interface supporting both real OpenAI API and an offline deterministic
    fallback engine for reproducible evaluation and testing without API keys.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL_ID", model)
        self.client = None

        if self.api_key and self.api_key != "replace_me" and OpenAI is not None:
            try:
                base_url = os.getenv("OPENAI_BASE_URL")
                self.client = OpenAI(api_key=self.api_key, base_url=base_url)
            except Exception:
                self.client = None

    def select_tool_and_args(self, request: str) -> Tuple[str, Dict[str, Any]]:
        """
        Parses user intent to select the appropriate tool and extract initial raw arguments.
        """
        if self.client:
            return self._openai_select_tool_and_args(request)
        return self._offline_select_tool_and_args(request)

    def extract_missing_field(self, tool_name: str, field_name: str, original_request: str) -> Any:
        """
        Targeted extraction prompt: Asks for only the missing field value.
        """
        if self.client:
            prompt = (
                f"The tool {tool_name} is missing the field '{field_name}'. "
                f"Based on the user's original request: '{original_request}', "
                f"what should this value be? Return only the value."
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            val = response.choices[0].message.content.strip().strip('"\'')
            return self._parse_scalar(val, field_name)

        return self._offline_extract_missing_field(tool_name, field_name, original_request)

    def correct_type_error(self, field_name: str, expected_format: str, bad_value: Any, original_request: str) -> Any:
        """
        Targeted type correction prompt: Translates invalid formats (e.g. 'tomorrow') into expected formats.
        """
        if self.client:
            prompt = (
                f"The field '{field_name}' requires format {expected_format}, "
                f"but you provided '{bad_value}'. Translate this into the correct format. "
                f"Original context: '{original_request}'. Return only the corrected value."
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            val = response.choices[0].message.content.strip().strip('"\'')
            return self._parse_scalar(val, field_name)

        return self._offline_correct_type(field_name, expected_format, bad_value, original_request)

    def repair_malformed_response(self, malformed_payload: Dict[str, Any], target_schema_json: str) -> Dict[str, Any]:
        """
        Targeted schema repair: Re-maps a malformed tool response back into the expected output schema.
        """
        if self.client:
            prompt = (
                f"The tool returned this malformed payload: {json.dumps(malformed_payload)}. "
                f"Extract the data to match this JSON schema: {target_schema_json}. "
                f"Return only a valid JSON object matching the schema."
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content.strip())

        return self._offline_repair_response(malformed_payload)

    # --------------------------------------------------------------------------
    # OpenAI Live Implementations
    # --------------------------------------------------------------------------

    def _openai_select_tool_and_args(self, request: str) -> Tuple[str, Dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "FlightSearch",
                    "description": "Search for flights between cities on a date",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "origin": {"type": "string"},
                            "destination": {"type": "string"},
                            "date": {"type": "string", "description": "ISO date YYYY-MM-DD"}
                        },
                        "required": ["origin", "destination"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "CalendarBooking",
                    "description": "Book a calendar event",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "event_title": {"type": "string"},
                            "start_time": {"type": "string", "description": "ISO datetime"},
                            "duration_minutes": {"type": "integer"}
                        },
                        "required": ["event_title"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "WeatherLookup",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {"type": "string"},
                            "unit": {"type": "string", "enum": ["C", "F"]}
                        },
                        "required": ["location"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "UnitConversion",
                    "description": "Convert value from one unit to another",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value": {"type": "number"},
                            "from_unit": {"type": "string"},
                            "to_unit": {"type": "string"}
                        },
                        "required": ["from_unit", "to_unit"]
                    }
                }
            }
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": request}],
            tools=tools,
            tool_choice="auto",
            temperature=0.0
        )
        msg = response.choices[0].message
        if msg.tool_calls:
            call = msg.tool_calls[0]
            name = call.function.name
            args = json.loads(call.function.arguments)
            return name, args

        return self._offline_select_tool_and_args(request)

    # --------------------------------------------------------------------------
    # Deterministic Offline Simulator
    # --------------------------------------------------------------------------

    def _offline_select_tool_and_args(self, text: str) -> Tuple[str, Dict[str, Any]]:
        text_lower = text.lower()

        # 1. FlightSearch intent
        if any(w in text_lower for w in ["flight", "fly", "plane", "ticket"]):
            # Match airport codes or city names
            # Look for patterns like "from JFK to LHR" or "to Paris"
            from_m = re.search(r"from\s+([A-Za-z]+)", text, re.IGNORECASE)
            to_m = re.search(r"to\s+([A-Za-z]+)", text, re.IGNORECASE)
            
            origin = from_m.group(1).upper() if from_m else None
            destination = to_m.group(1).upper() if to_m else None
            
            args: Dict[str, Any] = {}
            if origin:
                args["origin"] = origin
            if destination:
                args["destination"] = destination

            # Check for date in text
            iso_m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
            if iso_m:
                args["date"] = iso_m.group(1)
            elif "tomorrow" in text_lower:
                args["date"] = "tomorrow"  # Intentionally triggers type/format error
            elif "next tuesday" in text_lower:
                args["date"] = "next tuesday"
            # If no date mentioned at all, date is omitted -> triggers missing field

            return "FlightSearch", args

        # 2. CalendarBooking intent
        if any(w in text_lower for w in ["calendar", "schedule", "book", "meeting", "event", "sync"]):
            args: Dict[str, Any] = {}
            # Title
            title_m = re.search(r'(?:meeting|event|sync|titled|called)\s+["\']?([^"\',.]+)', text, re.IGNORECASE)
            args["event_title"] = title_m.group(1).strip() if title_m else "Meeting"

            # Duration
            dur_m = re.search(r"(\d+)\s*(?:min|minute|minutes|mins)", text_lower)
            if dur_m:
                args["duration_minutes"] = int(dur_m.group(1))
            elif "for an hour" in text_lower:
                args["duration_minutes"] = 60
            elif "twenty" in text_lower:
                args["duration_minutes"] = "twenty"  # Intentionally string type error
            # If duration omitted, triggers missing field

            # Start time
            iso_time_m = re.search(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\b", text)
            if iso_time_m:
                args["start_time"] = iso_time_m.group(1)
            elif "at " in text_lower:
                args["start_time"] = "tomorrow at 3pm"  # Type error
            else:
                args["start_time"] = "2026-09-20T10:00:00"

            return "CalendarBooking", args

        # 3. WeatherLookup intent
        if any(w in text_lower for w in ["weather", "temperature", "forecast", "climate"]):
            unit = "C"
            if "fahrenheit" in text_lower or re.search(r"\b(f|fahrenheit)\b", text_lower):
                unit = "F"
            elif "celsius" in text_lower or re.search(r"\b(c|celsius)\b", text_lower):
                unit = "C"
            elif "kelvin" in text_lower:
                unit = "Kelvin"  # Intentionally invalid enum

            loc_m = re.search(r"(?:in|for|at)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", text, re.IGNORECASE)
            raw_loc = loc_m.group(1).strip() if loc_m else "Tokyo"
            # Strip trailing unit letter if captured
            words = raw_loc.split()
            if words and words[-1].upper() in ("C", "F", "CELSIUS", "FAHRENHEIT"):
                words.pop()
            location = " ".join(words) if words else "Tokyo"

            return "WeatherLookup", {"location": location, "unit": unit}


        # 4. UnitConversion intent
        if any(w in text_lower for w in ["convert", "conversion", "miles", "km", "kg", "lbs"]):
            val_m = re.search(r"(\d+(?:\.\d+)?)", text)
            val = float(val_m.group(1)) if val_m else 10.0

            # Match units
            units_m = re.findall(r"\b(km|miles|kg|lbs|m|ft|celsius|fahrenheit|c|f)\b", text_lower)
            from_unit = units_m[0] if len(units_m) > 0 else "km"
            to_unit = units_m[1] if len(units_m) > 1 else "miles"

            args = {"value": val, "from_unit": from_unit, "to_unit": to_unit}
            if "without value" in text_lower:
                args.pop("value", None)  # triggers missing field
            return "UnitConversion", args

        # Default fallback
        return "WeatherLookup", {"location": text.strip(), "unit": "C"}

    def _offline_extract_missing_field(self, tool_name: str, field_name: str, text: str) -> Any:
        today_iso = date.today().isoformat()
        defaults = {
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "origin": "JFK",
            "destination": "LHR",
            "duration_minutes": 30,
            "start_time": f"{today_iso}T14:00:00",
            "event_title": "Project Sync",
            "location": "New York",
            "unit": "C",
            "value": 1.0,
            "from_unit": "km",
            "to_unit": "miles",
        }
        return defaults.get(field_name, "default_val")

    def _offline_correct_type(self, field_name: str, expected_format: str, bad_value: Any, original_request: str) -> Any:
        val_str = str(bad_value).lower()
        if field_name == "date":
            if "tomorrow" in val_str:
                return (date.today() + timedelta(days=1)).isoformat()
            if "tuesday" in val_str:
                return (date.today() + timedelta(days=4)).isoformat()
            return date.today().isoformat()

        if field_name == "duration_minutes":
            number_words = {"ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60}
            for word, num in number_words.items():
                if word in val_str:
                    return num
            return 30

        if field_name == "start_time":
            return f"{date.today().isoformat()}T15:00:00"

        if field_name == "unit":
            return "C"

        return bad_value

    def _offline_repair_response(self, malformed: Dict[str, Any]) -> Dict[str, Any]:
        """Re-map drifted payload keys back to canonical schema fields."""
        repaired: Dict[str, Any] = {}
        reverse_map = {
            "msg": "status",
            "response_status": "status",
            "flight_code": "flight_number",
            "departure_airport": "origin",
            "arrival_airport": "destination",
            "flight_date_str": "date",
            "fare_amount": "price",
            "meeting_title": "event_title",
            "time_iso": "start_time",
            "length_in_minutes": "duration_minutes",
            "reservation_id": "booking_id",
            "city_name": "location",
            "temp_reading": "temperature",
            "scale": "unit",
            "weather_desc": "condition",
            "input_val": "original_value",
            "output_val": "converted_value",
            "src_unit": "from_unit",
            "dst_unit": "to_unit",
        }

        for k, v in malformed.items():
            target_key = reverse_map.get(k)
            if target_key:
                repaired[target_key] = v

        # Normalize required defaults if missing
        if "status" not in repaired:
            repaired["status"] = "success"
        if "temperature" in repaired and isinstance(repaired["temperature"], str):
            try:
                repaired["temperature"] = float(repaired["temperature"])
            except ValueError:
                repaired["temperature"] = 20.0

        return repaired

    def _parse_scalar(self, val: str, field_name: str) -> Any:
        if field_name in ("duration_minutes",):
            try:
                return int(val)
            except ValueError:
                return val
        if field_name in ("value", "price", "temperature"):
            try:
                return float(val)
            except ValueError:
                return val
        return val
