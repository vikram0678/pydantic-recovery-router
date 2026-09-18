from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import ValidationError

from src.schemas import TOOL_INPUT_SCHEMAS, TOOL_OUTPUT_SCHEMAS
from src.tools import TOOL_REGISTRY
from src.llm_client import LLMClient


class RouterTrace:
    """Records diagnostic metadata and recovery attempts for each request."""
    def __init__(self) -> None:
        self.attempts: int = 0
        self.policies_triggered: List[str] = []
        self.tool_selected: Optional[str] = None
        self.error_reason: Optional[str] = None

    def record_attempt(self, policy_name: str) -> None:
        self.attempts += 1
        self.policies_triggered.append(policy_name)


def parse_validation_error(exc: ValidationError) -> Tuple[str, str, Any, str]:
    """
    Parses a Pydantic ValidationError to identify the error category,
    target field name, invalid value, and human-readable message.
    Categories: 'missing_field' or 'type_error'.
    """
    errors = exc.errors()
    first_err = errors[0] if errors else {}
    
    err_type = first_err.get("type", "")
    loc = first_err.get("loc", ("unknown",))
    field_name = str(loc[-1]) if loc else "unknown"
    bad_value = first_err.get("input")
    msg = first_err.get("msg", "")

    if err_type == "missing":
        return "missing_field", field_name, bad_value, msg
    
    # Int, float, datetime, enum, or custom value_error format issues
    return "type_error", field_name, bad_value, msg


def process_request(
    request: str,
    use_recovery: bool = True,
    llm_client: Optional[LLMClient] = None,
    trace: Optional[RouterTrace] = None
) -> Dict[str, Any]:
    """
    Orchestrates intent parsing, tool selection, argument validation, execution,
    and targeted fault recovery with a strictly bounded retry count of 1.

    Returns:
      - Validated output dictionary on success.
      - Explicit failure: {"status": "error", "reason": "<failure_class>_unrecoverable"}
    """
    if llm_client is None:
        llm_client = LLMClient()
    if trace is None:
        trace = RouterTrace()

    # --------------------------------------------------------------------------
    # Step 1: LLM Tool Selection and Initial Argument Extraction
    # --------------------------------------------------------------------------
    tool_name, raw_args = llm_client.select_tool_and_args(request)
    trace.tool_selected = tool_name

    if tool_name not in TOOL_INPUT_SCHEMAS or tool_name not in TOOL_REGISTRY:
        trace.error_reason = "unknown_tool_unrecoverable"
        return {"status": "error", "reason": "unknown_tool_unrecoverable"}

    input_model_cls = TOOL_INPUT_SCHEMAS[tool_name]
    output_model_cls = TOOL_OUTPUT_SCHEMAS[tool_name]
    tool_func = TOOL_REGISTRY[tool_name]

    # --------------------------------------------------------------------------
    # Step 2: Validate Input Arguments via Pydantic Boundary
    # --------------------------------------------------------------------------
    validated_input: Optional[Dict[str, Any]] = None
    try:
        validated_obj = input_model_cls(**raw_args)
        validated_input = validated_obj.model_dump()
    except ValidationError as val_err:
        errors = val_err.errors()
        missing_errors = [err for err in errors if err.get("type") == "missing"]
        
        category = "missing_field" if missing_errors else "type_error"

        if not use_recovery:
            # Baseline Mode: Give up immediately on first validation error
            reason = f"{category}_unrecoverable"
            trace.error_reason = reason
            return {"status": "error", "reason": reason}

        # Targeted Recovery bounded to 1 retry
        trace.record_attempt(category)

        if category == "missing_field":
            # Policy 1: Targeted Missing Field Re-prompt for each missing field
            for err in missing_errors:
                field_name = str(err["loc"][-1])
                resolved_value = llm_client.extract_missing_field(tool_name, field_name, request)
                raw_args[field_name] = resolved_value
        else:
            # Policy 2: Targeted Type Correction Re-prompt
            for err in errors:
                field_name = str(err["loc"][-1])
                bad_value = err.get("input")
                msg = err.get("msg", "")
                format_hint = msg or "proper standard format"
                corrected_value = llm_client.correct_type_error(field_name, format_hint, bad_value, request)
                raw_args[field_name] = corrected_value

        # Bounded Retry Attempt
        try:
            retry_obj = input_model_cls(**raw_args)
            validated_input = retry_obj.model_dump()
        except ValidationError:
            # Retry failed: give up explicitly without silent error
            reason = f"{category}_unrecoverable"
            trace.error_reason = reason
            return {"status": "error", "reason": reason}


    # --------------------------------------------------------------------------
    # Step 3: Tool Execution with Timeout Recovery
    # --------------------------------------------------------------------------
    raw_output: Optional[Dict[str, Any]] = None
    try:
        raw_output = tool_func(**validated_input)
    except TimeoutError:
        if not use_recovery:
            trace.error_reason = "timeout_unrecoverable"
            return {"status": "error", "reason": "timeout_unrecoverable"}

        # Policy 3: System-level Backoff and Retry (No LLM tokens used)
        trace.record_attempt("timeout_backoff")
        time.sleep(0.1)  # Bounded backoff delay

        try:
            raw_output = tool_func(**validated_input)
        except TimeoutError:
            # Second timeout exhausts retry bound
            trace.error_reason = "timeout_unrecoverable"
            return {"status": "error", "reason": "timeout_unrecoverable"}

    # --------------------------------------------------------------------------
    # Step 4: Output Validation & Schema Repair Strategy
    # --------------------------------------------------------------------------
    try:
        validated_output_obj = output_model_cls(**raw_output)
        return validated_output_obj.model_dump()
    except (ValidationError, TypeError):
        if not use_recovery:
            trace.error_reason = "schema_repair_unrecoverable"
            return {"status": "error", "reason": "schema_repair_unrecoverable"}

        # Policy 4: Schema Repair via targeted extraction prompt
        trace.record_attempt("schema_repair")
        target_schema_json = json.dumps(output_model_cls.model_json_schema())
        repaired_payload = llm_client.repair_malformed_response(raw_output, target_schema_json)

        try:
            repaired_output_obj = output_model_cls(**repaired_payload)
            return repaired_output_obj.model_dump()
        except (ValidationError, TypeError):
            trace.error_reason = "schema_repair_unrecoverable"
            return {"status": "error", "reason": "schema_repair_unrecoverable"}
