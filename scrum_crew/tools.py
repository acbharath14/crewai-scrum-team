"""Tools for the Scrum crew agents.

Kept deliberately small: small local models are fragile with complex
tool chains, so agents get file read/write and a test runner -- and
produce structured Markdown artifacts instead of long tool loops.

Confinement (the guardrail that actually binds): every file path an
agent names must resolve inside the repo directory, and test runs
must target the tests/ tree. A path that escapes is refused with a
plain message, not an exception, so the agent can correct itself.
Every successful write is appended to outputs/tool-calls.log, so a
human can audit exactly what the crew changed.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from crewai.tools import tool

ROOT = Path(__file__).resolve().parent.parent


def _resolve_within_repo(path, root=ROOT):
    """Resolve path against the repo root; None when it escapes.

    Relative paths anchor at the repo root (not the process working
    directory), and resolve() collapses '..' and symlinks, so neither
    traversal nor a symlink escape passes the check.
    """
    base = Path(root).resolve()
    candidate = Path(str(path).strip())
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


def _allowed_test_path(path, root=ROOT):
    """True when a run_tests target stays inside the tests/ tree.

    Node ids (tests/test_x.py::test_y) are checked on the file part.
    """
    base = Path(root).resolve()
    target = (path or "tests").strip()
    first = target.split("::")[0].strip()
    candidate = Path(first)
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base / "tests")
    except ValueError:
        return False
    return True


def _log_write(target, size):
    """Append one write record to outputs/tool-calls.log (best effort)."""
    try:
        log_path = ROOT / "outputs" / "tool-calls.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"{stamp} write {target} ({size} bytes)\n")
    except OSError:
        pass


@tool("read_file")
def read_file(path: str) -> str:
    """Read a text file and return its contents.

    Confined to the repo directory; anything outside is refused.
    """
    target = _resolve_within_repo(path, ROOT)
    if target is None or target.is_dir():
        return f"denied: {path!r} is outside the repo directory"
    return target.read_text(encoding="utf-8")


@tool("write_file")
def write_file(path_and_content: str) -> str:
    """Write content to a file.

    Input format: the file path, then a newline, then the content.
    Parent directories are created as needed. Confined to the repo
    directory; anything outside is refused and nothing is written.
    Every successful write is logged to outputs/tool-calls.log.
    """
    path, _, content = path_and_content.partition("\n")
    target = _resolve_within_repo(path, ROOT)
    if target is None or target.is_dir():
        return f"denied: {path!r} is outside the repo directory"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _log_write(target, len(content.encode("utf-8")))
    return f"wrote {target}"


@tool("run_tests")
def run_tests(path: str = "tests") -> str:
    """Run the pytest suite (default: tests/) and return a summary.

    Confined to the tests/ tree; anything else is refused without
    running. Output is truncated: agents need the verdict and the
    failing test names, not ten thousand lines of tracebacks.
    """
    if not _allowed_test_path(path, ROOT):
        return f"denied: run_tests is confined to tests/ (got {path!r})"
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
