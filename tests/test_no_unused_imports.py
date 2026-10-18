"""Regression test: keep unused imports (ruff F401) out of the codebase.

The source tree was cleaned of dead imports (see DEAD_CODE_REPORT.md — August
2026 audit). This test re-runs the same `ruff check --select F401` gate so any
new unused import fails CI instead of silently accumulating.

The lint scope matches the project's pre-commit configuration
(``app.py | src/ | scripts/``). The test skips when ruff is not installed
(e.g. runtime-only environments); CI installs `requirements_dev.txt`, which
includes ruff, so the guard is active there.
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Mirrors the `files` pattern in .pre-commit-config.yaml.
LINT_TARGETS = ["app.py", "src/", "scripts/"]

LINT_CMD = [
    sys.executable,
    "-m",
    "ruff",
    "check",
    "--select",
    "F401",
    "--output-format",
    "concise",
    *LINT_TARGETS,
]


def test_no_unused_imports_f401():
    # Availability guard: `python -m ruff` resolves the same interpreter that
    # runs pytest, so CI and local dev both use the installed tool.
    probe = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip(
            "ruff is not installed — run `pip install -r requirements.txt` "
            "to enable the F401 unused-import guard"
        )

    result = subprocess.run(LINT_CMD, cwd=PROJECT_ROOT, capture_output=True, text=True)

    assert result.returncode == 0, (
        "Unused imports detected (ruff F401). Remove the dead imports:\n"
        f"{result.stdout}\n{result.stderr}"
    )
