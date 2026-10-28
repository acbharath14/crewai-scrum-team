"""Tools for the Scrum crew agents.

Kept deliberately small: small local models are fragile with complex
tool chains, so agents get file read/write and a test runner -- and
produce structured Markdown artifacts instead of long tool loops.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from crewai.tools import tool


@tool("read_file")
def read_file(path: str) -> str:
    """Read a text file and return its contents."""
    return Path(path).read_text(encoding="utf-8")


@tool("write_file")
def write_file(path_and_content: str) -> str:
    """Write content to a file.

    Input format: the file path, then a newline, then the content.
    Parent directories are created as needed.
    """
    path, _, content = path_and_content.partition("\n")
    target = Path(path.strip())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {target}"


@tool("run_tests")
def run_tests(path: str = "tests") -> str:
    """Run the pytest suite (default: tests/) and return a summary.

    Output is truncated: agents need the verdict and the failing test
    names, not ten thousand lines of tracebacks.
    """
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", path, "-q"],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        return "test run timed out after 300s"
    tail = (proc.stdout + proc.stderr)[-3000:]
    verdict = "PASS" if proc.returncode == 0 else "FAIL"
    return f"tests: {verdict} (exit {proc.returncode})\n{tail}"


TOOLS_BY_NAME = {
    "read_file": read_file,
    "write_file": write_file,
    "run_tests": run_tests,
}
