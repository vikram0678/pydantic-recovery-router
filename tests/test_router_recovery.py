from __future__ import annotations

import pytest
from src.router import process_request, RouterTrace
from src.fault_injector import FaultContext


def test_happy_path_no_recovery_needed():
    """Valid request executes successfully with 0 recovery attempts."""
    FaultContext.set_fault("NONE")
    trace = RouterTrace()
    result = process_request("Book a flight from MIA to JFK on 2026-10-10", use_recovery=True, trace=trace)

    assert result.get("status") == "success"
    assert result.get("origin") == "MIA"
    assert result.get("destination") == "JFK"
    assert result.get("date") == "2026-10-10"
    assert trace.attempts == 0
    assert trace.policies_triggered == []


def test_missing_field_recovery():
    """Missing field triggers targeted re-prompt and succeeds on retry."""
    FaultContext.set_fault("NONE")
    trace = RouterTrace()
    result = process_request("Book a flight to Paris", use_recovery=True, trace=trace)

    assert result.get("status") == "success"
    assert "missing_field" in trace.policies_triggered
    assert trace.attempts == 1


def test_missing_field_baseline_fails():
    """Baseline mode without recovery immediately yields explicit error."""
    FaultContext.set_fault("NONE")
    trace = RouterTrace()
    result = process_request("Book a flight to Paris", use_recovery=False, trace=trace)

    assert result.get("status") == "error"
    assert result.get("reason") == "missing_field_unrecoverable"


def test_type_mismatch_recovery():
    """Natural language date triggers type correction and succeeds."""
    FaultContext.set_fault("NONE")
    trace = RouterTrace()
    result = process_request("Book a flight from JFK to LHR tomorrow", use_recovery=True, trace=trace)

    assert result.get("status") == "success"
    assert "type_error" in trace.policies_triggered
    assert trace.attempts == 1


def test_timeout_recovery_without_llm():
    """Timeout triggers system backoff retry and succeeds without LLM call."""
    FaultContext.set_fault("TIMEOUT", transient=True)
    trace = RouterTrace()
    result = process_request("Get weather in London C", use_recovery=True, trace=trace)

    assert result.get("status") == "success"
    assert result.get("location") == "London"
    assert "timeout_backoff" in trace.policies_triggered
    assert trace.attempts == 1
    FaultContext.reset()


def test_timeout_baseline_fails():
    """Baseline mode without recovery immediately fails on timeout."""
    FaultContext.set_fault("TIMEOUT", transient=True)
    result = process_request("Get weather in London C", use_recovery=False)

    assert result == {"status": "error", "reason": "timeout_unrecoverable"}
    FaultContext.reset()


def test_schema_repair_recovery():
    """Malformed tool payload triggers schema repair recovery."""
    FaultContext.set_fault("MALFORMED_RESPONSE", transient=True)
    trace = RouterTrace()
    result = process_request("Get the weather in Tokyo C", use_recovery=True, trace=trace)

    assert result.get("status") == "success"
    assert result.get("location") == "Tokyo"
    assert "schema_repair" in trace.policies_triggered
    assert trace.attempts == 1
    FaultContext.reset()


def test_schema_repair_baseline_fails():
    """Baseline mode without recovery immediately fails on malformed payload."""
    FaultContext.set_fault("MALFORMED_RESPONSE", transient=True)
    result = process_request("Get the weather in Tokyo C", use_recovery=False)

    assert result.get("status") == "error"
    assert result.get("reason") == "schema_repair_unrecoverable"
    FaultContext.reset()


def test_explicit_failure_when_bounds_exceeded():
    """Persistent failure exhausts 1-retry bound and returns explicit error."""
    FaultContext.set_fault("PERSISTENT_TIMEOUT", transient=False)
    result = process_request("Get the weather in Berlin C", use_recovery=True)

    assert result == {"status": "error", "reason": "timeout_unrecoverable"}
    FaultContext.reset()
