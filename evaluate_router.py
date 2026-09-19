from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from src.fault_injector import FaultContext
from src.router import RouterTrace, process_request
from src.schemas import TOOL_OUTPUT_SCHEMAS


def load_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    """Loads JSONL evaluation entries."""
    if not dataset_path.exists():
        raise FileNotFoundError(f"Evaluation dataset not found at: {dataset_path}")
    
    cases: List[Dict[str, Any]] = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"Warning: Skipping invalid JSON line {line_num}: {exc}", file=sys.stderr)
    return cases


def is_valid_payload(tool_name: str, payload: Dict[str, Any]) -> bool:
    """Validates returned payload against the designated Pydantic output schema."""
    if not isinstance(payload, dict) or payload.get("status") == "error":
        return False
    
    schema_cls = TOOL_OUTPUT_SCHEMAS.get(tool_name)
    if not schema_cls:
        return False
    
    try:
        schema_cls(**payload)
        return True
    except Exception:
        return False


def run_evaluation_pass(cases: List[Dict[str, Any]], use_recovery: bool) -> Dict[str, float]:
    """Runs all test cases through the router in either baseline or recovery mode."""
    total_cases = len(cases)
    if total_cases == 0:
        return {"completion_rate": 0.0, "silent_wrong_rate": 0.0, "mean_recovery_attempts": 0.0}

    valid_successes = 0
    silent_wrongs = 0
    total_attempts = 0

    for item in cases:
        req_text = item.get("request", "")
        expected_tool = item.get("expected_tool", "")
        fault = item.get("injected_fault", "NONE")
        is_transient = fault != "PERSISTENT_TIMEOUT"

        FaultContext.set_fault(fault, transient=is_transient)
        trace = RouterTrace()

        try:
            result = process_request(req_text, use_recovery=use_recovery, trace=trace)
        except Exception as exc:
            result = {"status": "error", "reason": f"unhandled_exception_{type(exc).__name__}"}
        finally:
            FaultContext.reset()

        total_attempts += trace.attempts
        is_error = result.get("status") == "error"
        is_valid = is_valid_payload(expected_tool, result)

        if not is_error and is_valid:
            valid_successes += 1
        elif not is_error and not is_valid:
            silent_wrongs += 1

    completion_rate = round(valid_successes / total_cases, 4)
    silent_wrong_rate = round(silent_wrongs / total_cases, 4)
    mean_recovery_attempts = round(total_attempts / total_cases, 4)

    return {
        "completion_rate": completion_rate,
        "silent_wrong_rate": silent_wrong_rate,
        "mean_recovery_attempts": mean_recovery_attempts,
    }


def main() -> None:
    repo_root = Path(__file__).resolve().parent
    data_file = repo_root / "data" / "eval.jsonl"
    output_dir = repo_root / "output"
    output_file = output_dir / "metrics.json"
    results_dir = repo_root / "results"
    results_file = results_dir / "metrics.json"

    output_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading evaluation dataset from: {data_file}")
    cases = load_dataset(data_file)
    print(f"Loaded {len(cases)} test cases.\n")

    print("Running Baseline Mode (no recovery)...")
    baseline_metrics = run_evaluation_pass(cases, use_recovery=False)

    print("Running Recovery Mode (targeted policies active)...")
    recovery_metrics = run_evaluation_pass(cases, use_recovery=True)

    metrics = {
        "baseline": baseline_metrics,
        "recovery_active": recovery_metrics,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nSaved benchmark metrics to: {output_file}\n")
    print("=" * 60)
    print("                 BENCHMARK SUMMARY RESULTS")
    print("=" * 60)
    print(f"{'Metric':<25} | {'Baseline':<12} | {'Recovery Active':<15}")
    print("-" * 60)
    print(f"{'Completion Rate':<25} | {baseline_metrics['completion_rate']:<12.2%} | {recovery_metrics['completion_rate']:<15.2%}")
    print(f"{'Silent Wrong Rate':<25} | {baseline_metrics['silent_wrong_rate']:<12.2%} | {recovery_metrics['silent_wrong_rate']:<15.2%}")
    print(f"{'Mean Recovery Attempts':<25} | {baseline_metrics['mean_recovery_attempts']:<12.2f} | {recovery_metrics['mean_recovery_attempts']:<15.2f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
