#!/usr/bin/env python3
"""Prerequisite setup for the CrewAI Scrum Team repo.

Run once after cloning, from anywhere (the script finds the repo root
from its own location):

    python3 scripts/setup.py

What it does, in order (every step is idempotent -- re-running skips
what is already done):

  1. Checks Python 3.10+.
  2. Creates .venv if missing (reuses it if present; --recreate-venv
     rebuilds it).
  3. Upgrades pip inside the venv (best effort).
  4. Installs requirements.txt into the venv. On Intel macOS the
     normal install fails: LanceDB ships no Intel (x86_64) macOS wheel
     after 0.25.3, while CrewAI 1.15.30 requires lancedb>=0.33.0. In
     that case the script installs CrewAI without LanceDB (crewai
     --no-deps plus CrewAI's other dependencies, parsed from the wheel
     metadata) and then proves the crew still builds -- this repo's
     crews use artifact handoffs, not CrewAI memory, so LanceDB is
     never imported at runtime. On Intel macOS the fallback also pins
     cryptography==48.0.1, the newest version with an Intel wheel
     (50.x has none and falls back to a failing Rust source build).
     Set SCRUM_SETUP_FORCE_FALLBACK=1 to exercise the fallback path on
     any platform (debugging aid).
  5. Checks Ollama: starts a background `ollama serve` if the server
     is not reachable, then pulls the default model (qwen3:8b, or
     $OLLAMA_MODEL) if it is not already present. Ollama itself is
     never installed by this script -- if the binary is missing it
     prints the install command and reports that step as pending.
  6. Verifies: runs the pytest suite, then the scripted demo
     (no LLM needed). Both must pass.

Flags:
  --skip-ollama    skip step 5 (deps + verification only)
  --skip-verify    skip step 6
  --recreate-venv  delete .venv and rebuild it from scratch

Exit status is 0 only when every attempted step passes (a skipped
Ollama step does not count against --skip-ollama runs).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent.parent
OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")


def log(message):
    print(f"setup: {message}")


def fail(message):
    print(f"setup: FATAL: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_captured(cmd, cwd=ROOT):
    """Run cmd, capturing output; return the CompletedProcess."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def print_tail(proc, limit=3000):
    tail = (proc.stdout + proc.stderr)[-limit:]
    if tail.strip():
        print(tail, file=sys.stderr)


def check_python():
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
             f"found {sys.version.split()[0]}")
    log(f"Python {sys.version.split()[0]} OK")


def venv_python_path(venv_dir):
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def ensure_venv(recreate):
    venv_dir = ROOT / ".venv"
    if recreate and venv_dir.exists():
        log("removing existing .venv (--recreate-venv)")
        shutil.rmtree(venv_dir)
    if venv_dir.exists():
        venv_python = venv_python_path(venv_dir)
        proc = run_captured([str(venv_python), "--version"])
        if proc.returncode == 0:
            log(f"reusing existing .venv ({proc.stdout.strip()})")
            return venv_python
        fail(f".venv exists but its Python does not run "
             f"({venv_python}); re-run with --recreate-venv")
    log("creating .venv")
    proc = run_captured([sys.executable, "-m", "venv", str(venv_dir)])
    if proc.returncode != 0:
        print_tail(proc)
        fail("could not create .venv")
    venv_python = venv_python_path(venv_dir)
    log("created .venv")
    return venv_python


def upgrade_pip(venv_python):
    proc = run_captured([str(venv_python), "-m", "pip", "install",
                         "--upgrade", "pip"])
    if proc.returncode == 0:
        log("pip upgraded in .venv")
    else:
        log("WARNING: pip upgrade failed, continuing with existing pip")


def read_requirements():
    """Parse requirements.txt into (name, raw_line) pairs."""
    req_path = ROOT / "requirements.txt"
    if not req_path.exists():
        fail("requirements.txt not found -- is this script inside the repo?")
    reqs = []
    for line in req_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"([A-Za-z0-9_.\-]+)", line)
        if not match:
            fail(f"cannot parse requirements line: {line!r}")
        reqs.append((match.group(1), line))
    return reqs


def wheel_deps_without_lancedb(wheel_path):
    """Read a wheel's METADATA Requires-Dist list, minus lancedb."""
    with zipfile.ZipFile(wheel_path) as archive:
        metadata_name = next(
            (n for n in archive.namelist() if n.endswith("/METADATA")),
            None)
        if metadata_name is None:
            fail(f"no METADATA found in {wheel_path}")
        text = archive.read(metadata_name).decode("utf-8", "replace")
    deps = []
    for line in text.splitlines():
        if not line.startswith("Requires-Dist: "):
            continue
        req = line[len("Requires-Dist: "):].strip()
        match = re.match(r"([A-Za-z0-9_.\-]+)", req)
        if match and match.group(1).lower() == "lancedb":
            continue
        deps.append(req)
    return deps


def verify_crew_builds(venv_python):
    proc = run_captured(
        [str(venv_python), "-c",
         "from scrum_crew.crew import build_planning_crew; "
         "build_planning_crew(); print('crew builds OK')"])
    if proc.returncode != 0:
        print_tail(proc)
        fail("crew does not build in this venv")
    log("crew builds OK")


def install_without_lancedb(venv_python, reqs):
    """Install CrewAI without LanceDB (Intel macOS wheel gap)."""
    crew = next((raw for name, raw in reqs if name.lower() == "crewai"),
                None)
    if crew is None:
        fail("crewai not in requirements.txt, cannot apply lancedb fallback")
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = run_captured([str(venv_python), "-m", "pip", "download",
                             crew, "--no-deps", "-d", tmpdir])
        if proc.returncode != 0:
            print_tail(proc)
            fail("could not download the crewai wheel for inspection")
        wheels = list(Path(tmpdir).glob("*.whl"))
        if len(wheels) != 1:
            fail(f"expected one crewai wheel, found {len(wheels)}")
        deps = wheel_deps_without_lancedb(wheels[0])
    log(f"installing {crew} without lancedb "
        f"({len(deps)} other dependencies from its metadata)")
    proc = run_captured([str(venv_python), "-m", "pip", "install",
                         crew, "--no-deps"])
    if proc.returncode != 0:
        print_tail(proc)
        fail("could not install crewai --no-deps")
    install_list = list(deps)
    if sys.platform == "darwin" and platform.machine() == "x86_64":
        # Newest cryptography with an Intel wheel (50.x has none); without
        # this pip picks 50.x and falls back to a failing Rust source build.
        install_list.append("cryptography==48.0.1")
        log("Intel macOS: pinning cryptography==48.0.1 "
            "(newest with an Intel wheel)")
    proc = run_captured([str(venv_python), "-m", "pip", "install",
                         *install_list])
    if proc.returncode != 0:
        print_tail(proc)
        fail("could not install crewai's dependencies (minus lancedb)")
    others = [raw for name, raw in reqs if name.lower() != "crewai"]
    if others:
        proc = run_captured([str(venv_python), "-m", "pip", "install",
                             *others])
        if proc.returncode != 0:
            print_tail(proc)
            fail("could not install the remaining requirements")
    log("installed without lancedb: this repo's crews use artifact "
        "handoffs, not CrewAI memory, so lancedb is never imported")
    verify_crew_builds(venv_python)


def install_requirements(venv_python):
    """Install requirements.txt; returns 'full' or 'no-lancedb'."""
    if os.environ.get("SCRUM_SETUP_FORCE_FALLBACK") == "1":
        log("forcing lancedb-free fallback (SCRUM_SETUP_FORCE_FALLBACK=1)")
        install_without_lancedb(venv_python, read_requirements())
        return "no-lancedb"
    proc = run_captured([str(venv_python), "-m", "pip", "install",
                         "-r", str(ROOT / "requirements.txt")])
    if proc.returncode == 0:
        log("requirements installed")
        return "full"
    combined = (proc.stdout + proc.stderr).lower()
    if "lancedb" in combined:
        log("normal install failed on lancedb (no Intel macOS wheel "
            "for lancedb>=0.33) -- falling back to install without it")
        install_without_lancedb(venv_python, read_requirements())
        return "no-lancedb"
    print_tail(proc)
    fail("pip install -r requirements.txt failed")


def ollama_reachable():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags",
                                    timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def ollama_models():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags",
                                    timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        fail(f"could not list Ollama models: {exc}")
    return [m.get("name", "") for m in data.get("models", [])]


def ensure_ollama():
    """Make sure the Ollama server runs and the model is present.

    Returns True when both hold. Returns False (with a printed fix)
    when the Ollama binary is missing, the server cannot be started,
    or the model pull fails -- the caller still runs verification and
    reports Ollama as pending.
    """
    if shutil.which("ollama") is None:
        log("WARNING: `ollama` is not on PATH; skipping server + model")
        log("  install it, then re-run this script (it resumes):")
        if sys.platform == "darwin":
            log("    download the Ollama app from https://ollama.com/download")
        elif sys.platform.startswith("linux"):
            log("    curl -fsSL https://ollama.com/install.sh | sh")
        else:
            log("    download the installer from https://ollama.com/download")
        return False
    if ollama_reachable():
        log("Ollama server already reachable at localhost:11434")
    else:
        log("starting background `ollama serve`")
        log_path = ROOT / ".ollama-serve.log"
        log_file = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            ["ollama", "serve"],
            stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"))
        reachable = False
        for _ in range(15):
            import time
            time.sleep(2)
            if ollama_reachable():
                reachable = True
                break
        if not reachable:
            log("WARNING: `ollama serve` did not become reachable")
            log(f"  server log: {log_path}")
            log("  fix with: run `ollama serve` in another terminal "
                "(or open the Ollama app), then re-run this script")
            return False
        log(f"started background `ollama serve` (PID {proc.pid}, "
            f"log {log_path}; stop with: kill {proc.pid})")
    names = ollama_models()
    wanted = DEFAULT_MODEL
    present = wanted in names or (
        ":" not in wanted and wanted + ":latest" in names)
    if present:
        log(f"model {wanted} already present")
        return True
    log(f"pulling model {wanted} (one-time download, several GB)...")
    proc = subprocess.run(["ollama", "pull", wanted])
    if proc.returncode != 0:
        log(f"WARNING: `ollama pull {wanted}` failed; re-run this script "
            f"after checking your network, or pull it manually")
        return False
    if wanted in ollama_models() or (
            ":" not in wanted and wanted + ":latest" in ollama_models()):
        log(f"model {wanted} pulled")
        return True
    log(f"WARNING: model {wanted} still not listed after pull")
    return False


def verify(venv_python):
    proc = subprocess.run([str(venv_python), "-m", "pytest",
                           "tests/", "-q"])
    if proc.returncode != 0:
        fail("pytest suite failed")
    log("pytest suite passed")
    proc = subprocess.run([str(venv_python), "-m", "scrum_crew.run",
                           "--demo"])
    if proc.returncode != 0:
        fail("scripted demo failed")
    log("scripted demo passed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-ollama", action="store_true",
                        help="skip the Ollama server + model steps")
    parser.add_argument("--skip-verify", action="store_true",
                        help="skip the pytest + demo verification")
    parser.add_argument("--recreate-venv", action="store_true",
                        help="delete .venv and rebuild it from scratch")
    args = parser.parse_args(argv)

    check_python()
    venv_python = ensure_venv(args.recreate_venv)
    upgrade_pip(venv_python)
    deps_mode = install_requirements(venv_python)

    ollama_ok = True
    if not args.skip_ollama:
        ollama_ok = ensure_ollama()
    else:
        log("Ollama steps skipped (--skip-ollama)")

    if not args.skip_verify:
        verify(venv_python)
    else:
        log("verification skipped (--skip-verify)")

    rel_python = venv_python.relative_to(ROOT)
    print()
    print("setup: summary")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  venv: {venv_python}")
    print(f"  deps: {'OK' if deps_mode == 'full' else 'OK (without lancedb)'}")
    if args.skip_ollama:
        print("  Ollama: skipped")
    elif ollama_ok:
        print(f"  Ollama: server reachable, model {DEFAULT_MODEL} present")
    else:
        print("  Ollama: PENDING (see warnings above)")
    print(f"  tests/demo: {'passed' if not args.skip_verify else 'skipped'}")
    if ollama_ok or args.skip_ollama:
        print()
        print("setup: ready. Run the real crew with:")
        print(f"  {rel_python} -m scrum_crew.run")
        print(f"  {rel_python} -m scrum_crew.run --auto   "
              f"(skip approval gates)")
        return 0
    print()
    print("setup: everything except Ollama is done. Fix Ollama, then "
          "re-run this script -- it resumes where it left off.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
