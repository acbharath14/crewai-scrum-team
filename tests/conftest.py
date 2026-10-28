"""Preflight hook: the standing preflight rule, wired into pytest.

Before the suite runs, scripts/preflight.py --test-deps-only executes:
it checks the Python version and installs pytest when missing (failing
fast on install errors). Ollama and CrewAI are only warned about here --
the suite must pass with neither installed.

Skip with: SCRUM_SKIP_PREFLIGHT=1 pytest
"""

import os
import subprocess
import sys

if os.environ.get("SCRUM_SKIP_PREFLIGHT") != "1":
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _proc = subprocess.run(
        [sys.executable, os.path.join(_root, "scripts", "preflight.py"),
         "--test-deps-only"],
        capture_output=True, text=True, timeout=180,
    )
    if _proc.returncode != 0:
        print("preflight warning (continuing anyway):",
              _proc.stdout.strip(), _proc.stderr.strip(), file=sys.stderr)
