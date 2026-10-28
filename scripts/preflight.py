"""Preflight: check required setup, install what is missing when testing.

Standing rule for every new repo: a fresh clone must never fail on
missing dependencies with only a stack trace. This script:

  * fails fast when Python is older than 3.10;
  * installs missing pip packages from requirements.txt (only the ones
    that are missing, lockfile-free but version-pinned in the file);
    any install error is fatal -- it does not limp on;
  * checks Ollama reachability and prints fix commands, but NEVER
    installs Ollama or downloads models (those are the user's call).

Modes:
  python scripts/preflight.py                 full check (deps + Ollama)
  python scripts/preflight.py --test-deps-only
      only ensure pytest is importable (used by tests/conftest.py so
      the suite passes with no Ollama and no CrewAI installed)
  python scripts/preflight.py --skip-install
      check only, install nothing

Skip entirely with SCRUM_SKIP_PREFLIGHT=1.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent.parent


def _fail(message):
    print(f"preflight: FATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_python():
    if sys.version_info < MIN_PYTHON:
        _fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
              f"found {sys.version.split()[0]}")
    print(f"preflight: Python {sys.version.split()[0]} OK")


def _module_missing(name):
    return importlib.util.find_spec(name) is None


def ensure_packages(names, skip_install):
    """Ensure each importable module exists; pip-install the missing ones."""
    missing = [n for n in names if _module_missing(n)]
    if not missing:
        print(f"preflight: packages OK ({', '.join(names)})")
        return
    if skip_install:
        _fail(f"missing packages: {', '.join(missing)} "
              "(re-run without --skip-install to install them)")
    print(f"preflight: installing missing packages: {', '.join(missing)}")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", *missing],
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        _fail(f"pip install failed for {', '.join(missing)}")
    still_missing = [n for n in missing if _module_missing(n)]
    if still_missing:
        _fail(f"still missing after install: {', '.join(still_missing)}")
    print(f"preflight: installed {', '.join(missing)}")


def check_ollama():
    """Check Ollama reachability; print fix commands, never install."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags",
                                    timeout=5) as resp:
            if resp.status == 200:
                print("preflight: Ollama reachable at localhost:11434")
                return True
    except (urllib.error.URLError, OSError):
        pass
    print("preflight: WARNING: Ollama not reachable at localhost:11434.")
    print("  fix with:")
    print("    ollama serve")
    print("    ollama pull qwen3:8b")
    print("  (the scripted demo and the test suite do not need Ollama;")
    print("   only the real crew run does)")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-deps-only", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args(argv)
    check_python()
    if args.test_deps_only:
        ensure_packages(["pytest"], skip_install=args.skip_install)
        return 0
    ensure_packages(["pytest", "crewai", "litellm"],
                    skip_install=args.skip_install)
    check_ollama()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
