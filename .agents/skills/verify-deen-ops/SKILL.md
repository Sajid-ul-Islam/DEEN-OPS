---
name: verify-deen-ops
description: >-
  Use this skill to run the required quality gates, unit test suite (360+ tests),
  and 65-module import verification before concluding any code changes in DEEN-OPS Terminal.
---

# DEEN-OPS Verification & Quality Gate

Run this verification workflow before concluding any refactor, feature addition, or bug fix.

## Quality Gate Criteria
- **Unit Tests**: All 360+ unit tests in `tests/` must pass with 0 failures.
- **Module Imports**: All 65 modules in `scripts/check_imports.py` must report `OK` with 0 failures.

## Verification Steps

### Step 1: Run Full Unit Test Suite

**Windows (PowerShell)**:
```powershell
$env:PYTHONPATH="."
py -m pytest tests/ -v
```

**Linux / macOS (Bash)**:
```bash
PYTHONPATH=. python -m pytest tests/ -v
```

### Step 2: Run Module Import Check

**Windows (PowerShell)**:
```powershell
py scripts/check_imports.py
```

**Linux / macOS (Bash)**:
```bash
python scripts/check_imports.py
```

### Step 3: Evaluate Results
- If any test or import fails, inspect the traceback and resolve the issue before proceeding.
- Ensure no new files violate the strict layer separation rules defined in `AGENTS.md`.
