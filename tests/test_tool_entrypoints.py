"""The entry points, run the way the player and the build actually run them.

Two of these matter more than the rest and are checked in a *clean* subprocess with
no ``PYTHONPATH`` set: the frozen exe is built from ``tools/dfboss_main.py``, and
``python -m dfbossreminder`` is the no-install path. A test that only imported the
package in-process would pass even if neither of those could find it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def clean_env() -> dict:
    """The environment a fresh console has: no PYTHONPATH pointing at this project."""
    env = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(name, None)
    return env


def run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=60,
                          env=env if env is not None else clean_env(), cwd=str(PROJECT_ROOT))


def test_the_module_entry_point_needs_no_install() -> None:
    env = clean_env()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    result = run([PYTHON, "-m", "dfbossreminder", "--show-config",
                  "--settings", "/nonexistent/settings.json"], env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["user_id"] == ""


def test_the_packaging_entry_script_finds_the_package_with_no_pythonpath() -> None:
    # This is the file build-exe.cmd hands to PyInstaller, so it has to bootstrap
    # src/ itself; a clean environment proves it does.
    result = run([PYTHON, "tools/dfboss_main.py", "--show-config",
                  "--settings", "/nonexistent/settings.json"])
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["base_url"]


def test_the_entry_script_sets_the_radius_from_the_command_line() -> None:
    result = run([PYTHON, "tools/dfboss_main.py", "--show-config", "--radius", "17",
                  "--settings", "/nonexistent/settings.json"])
    assert json.loads(result.stdout)["radius_blocks"] == 17


def test_the_help_lists_the_requirements_as_options() -> None:
    result = run([PYTHON, "tools/dfboss_main.py", "--help"])
    assert result.returncode == 0
    for option in ("--user-id", "--radius", "--highlight", "--presentation"):
        assert option in result.stdout, f"{option} must be a documented option"


def test_every_windows_script_is_present_and_ascii_only() -> None:
    # PowerShell 5.1 reads a BOM-less script as ANSI, so a non-ASCII character can
    # swallow the next quote and point the error at the wrong line.
    scripts = ["build-exe.cmd", "run-dfboss.ps1", "stop-dfboss.ps1", "capture-panel.ps1",
               "dfb-interactive.cmd"]
    for name in scripts:
        path = PROJECT_ROOT / "tools" / "pc" / name
        assert path.exists(), f"{name} is missing"
        raw = path.read_bytes()
        non_ascii = [byte for byte in raw if byte > 0x7F]
        assert not non_ascii, f"{name} must be ASCII-only, found {len(non_ascii)} non-ASCII bytes"


def test_the_remote_runner_gives_each_run_its_own_output_file() -> None:
    # One shared .run-out.txt broke as soon as a command left a background process
    # behind: the process inherits the file's handle, so the file can be neither deleted
    # nor rewritten, and every later run polls a token that nobody will ever write -
    # which reads as "the PC is hung". The token has to reach the task wrapper somehow,
    # and a scheduled task cannot be given an argument, so it travels in a file.
    runner = (PROJECT_ROOT / "tools" / "run_on_pc.sh").read_text(encoding="utf-8")
    assert ".run-out-$run_token.txt" in runner
    assert ".run-token.txt" in runner
    wrapper = (PROJECT_ROOT / "tools" / "pc" / "dfb-interactive.cmd").read_text(encoding="utf-8")
    assert 'set /p TOKEN=<".run-token.txt"' in wrapper
    assert 'set "OUT=.run-out-%TOKEN%.txt"' in wrapper


def test_the_remote_runner_spells_the_path_for_each_caller() -> None:
    # findstr and del reject a path whose last separator is a forward slash - findstr
    # says "cannot open", del says nothing - while scp wants the forward-slash form. When
    # both used one spelling, the poll never matched and reported a timeout on runs that
    # had in fact finished.
    runner = (PROJECT_ROOT / "tools" / "run_on_pc.sh").read_text(encoding="utf-8")
    assert 'remote_out_shell="$REMOTE_REPO\\\\.run-out-$run_token.txt"' in runner
    assert 'remote_out="$REMOTE_REPO/.run-out-$run_token.txt"' in runner
    # Every findstr and del call must use the shell spelling, every scp the other one.
    code = [line for line in runner.splitlines() if not line.lstrip().startswith("#")]
    for line in code:
        if "findstr" in line or "del /q" in line:
            assert "remote_out_shell" in line, line
        if "scp " in line and "run-out" in line:
            assert "remote_out" in line and "remote_out_shell" not in line, line
