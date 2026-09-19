# Pydantic Recovery Router

An AI function-calling orchestration layer that replaces blind retry loops with typed Pydantic validation boundaries, deterministic fault injection, and bounded failure recovery.

## Features

- **Pydantic Validation Boundary**: Validates LLM tool arguments and external API return payloads with Pydantic v2 schemas.
- **4 Targeted Recovery Policies**: Dedicated recovery logic for missing fields, invalid formats, timeouts, and malformed responses.
- **Zero-Token Timeout Backoff**: Retries transient server timeouts directly at the Python level without invoking the LLM.
- **Bounded 1-Retry Limit**: Explicit give-up on persistent failures to eliminate silent wrong responses.
- **Deterministic Fault Injector**: Middleware that simulates timeouts and schema drift on demand for testing.
- **Comparative Evaluation**: Automated harness measuring completion rate and silent-wrong rate across 60 test cases.

---

## Architecture Overview

```text
+-------------------------------------------------------------+
|                 Natural Language Request                    |
+------------------------------+------------------------------+
                               |
                               | (1. Intent Parsing & Tool Selection)
                               v
+-------------------------------------------------------------+
|                     LLM Extraction API                      |
|                   [ Emits Raw JSON Args ]                   |
+------------------------------+------------------------------+
                               |
                               | (2. Pydantic Input Validation)
                               v
                        /─────────────\
                       ( Args Valid?   )
                        \─────────────/
                        /             \
                  YES  /               \  NO
                      /                 \
                     v                   v
+-----------------------------+   +------------------------------------+
|  Fault Injector Middleware  |   |     Targeted Input Recovery        |
|  - Pass-through (NONE)      |   |  - Missing: Targeted Re-prompt     |
|  - Injects TIMEOUT          |   |  - Type: Format Translation        |
|  - Injects MALFORMED        |   |  (Bounded to 1 Retry)              |
+--------------+--------------+   +-----------------+------------------+
               |                                    |
               | (3. Execute Tool)                  | (Retry 1)
               v                                    v
        /─────────────\                             |
       (   Timeout?    )                           |
        \─────────────/                             |
        /             \                             |
   NO  /               \  YES                       |
      v                 v                           |
+──────────────+  +─────────────────────────+       |
| Mock Tools   |  | System Backoff & Retry  |       |
| Execution    |  | (0 LLM Tokens / Bounded)|       |
+──────+───────+  +─────────────+───────────+       |
       |                        |                   |
       | (4. Output Payload)    +-------------------+
       v
+-----------------------------+
| Pydantic Output Validator   |
+--------------+--------------+
               |
               v
        /─────────────\
       ( Schema Drift? )
        \─────────────/
        /             \
   NO  /               \  YES
      v                 v
+──────────────+  +─────────────────────────+
| Valid Success|  | Response Schema Repair  |
| Output JSON  |  | (Targeted LLM Prompt)   |
+──────+───────+  +─────────────+───────────+
       |                        |
       |                        | (Bounded to 1 Retry)
       |                        v
       |          +─────────────────────────+
       |          | Explicit Give-Up        |
       |          | (If Retry Bound Exceeds)|
       |          +─────────────+───────────+
       |                        |
       +───────────+────────────+
                   |
                   v
+-------------------------------------------------------------+
|                 Final Standardized Response                 |
+-------------------------------------------------------------+
```

### Understanding the Architecture
The diagram above illustrates the separation of concerns across the system:
1. **Intent Parsing & Extraction**: When the user submits a natural language query, the router prompts the LLM to select a tool and extract initial raw arguments.
2. **Validation Boundary**: Raw arguments immediately hit the Pydantic Schema Validator. If validation fails, the error type determines whether the **Missing Field Re-prompt** or **Type Correction Re-prompt** policy is triggered.
3. **Execution & Fault Injection**: If validation passes, the request moves to the Fault Injector Middleware wrapping the mock tools. If a timeout is injected, the **System Backoff and Retry** policy catches it and re-invokes the tool directly without bothering the LLM.
4. **Schema Repair & Bounded Give-Up**: When the tool returns data, it is validated against the expected output schema. If malformed, the **Response Schema Repair** policy extracts the data into the canonical structure. If any policy exceeds its 1-retry bound, the system safely routes to an **Explicit Give-Up** state rather than returning a fabricated success.

---

## Getting Started

### Prerequisites

- **Docker & Docker Compose** (Recommended) or **Python 3.10+**
- **Git**

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/vikram0678/pydantic-recovery-router.git
   cd pydantic-recovery-router
   ```

---

## Usage

### 1. Run with Docker Compose (Recommended)
Run the entire test and evaluation suite inside an isolated container with a single command:
```bash
docker compose up --build
```
This automatically runs unit tests (`pytest -v`), runs the evaluation harness (`python evaluate_router.py`), and writes the results to `output/metrics.json`.

### 2. Run Locally with Python
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Linux / macOS
.venv\Scripts\activate          # On Windows

# Install dependencies
pip install -r requirements.txt

# Run the comparative evaluation harness
python evaluate_router.py
```

### 3. Run Unit Tests
Execute the 18 automated contract tests:
```bash
pytest -v
```

---

## Benchmark Results

Evaluation across 60 test cases with a 40% injected fault mix:

```
============================================================
                 BENCHMARK SUMMARY RESULTS
============================================================
Metric                    | Baseline     | Recovery Active
------------------------------------------------------------
Completion Rate           | 46.67%       | 96.67%         
Silent Wrong Rate         | 0.00%        | 0.00%          
Mean Recovery Attempts    | 0.00         | 0.53           
============================================================
```

- **Completion Rate**: Increased from **46.67%** (baseline) to **96.67%** with targeted recovery active.
- **Silent Wrong Rate**: Maintained at **0.00%** because unrecoverable failures explicitly give up rather than hallucinating success.
- **Mean Recovery Attempts**: Averaged **0.53** retries per request across the fault mix.

---

## Repository Layout

```
├── .dockerignore             # Docker build exclusions
├── .env.example              # Environment variables template
├── .gitignore                # Git exclusions
├── Dockerfile                # Evaluation container image
├── docker-compose.yml        # Compose service configuration mounting ./output
├── evaluate_router.py        # Comparative batch evaluation harness
├── requirements.txt          # Pinned dependencies
├── data/
│   └── eval.jsonl            # 60 evaluation test cases
├── output/
│   └── metrics.json          # Benchmark metrics output
├── results/
│   └── metrics.json          # Persisted metrics copy
├── src/
│   ├── __init__.py
│   ├── fault_injector.py     # Fault injection middleware and context
│   ├── llm_client.py         # OpenAI SDK client + deterministic offline engine
│   ├── router.py             # 7-step router with 4 targeted recovery policies
│   ├── schemas.py            # Pydantic input & output models
│   └── tools.py              # Mock tool implementations
└── tests/
    ├── __init__.py
    ├── test_router_recovery.py
    └── test_schemas_and_faults.py
```

---

## Contributing

1. Fork the repository.
2. Create a feature branch (`git checkout -b feature/new-feature`).
3. Commit your changes (`git commit -m "feat: add feature"`).
4. Push to the branch (`git push origin feature/new-feature`).
5. Open a Pull Request.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## Contact / Support

- **Author**: Vikram Nandimandalam
- **Repository**: [https://github.com/vikram0678/pydantic-recovery-router](https://github.com/vikram0678/pydantic-recovery-router)
- **Issues**: [https://github.com/vikram0678/pydantic-recovery-router/issues](https://github.com/vikram0678/pydantic-recovery-router/issues)
