"""Prove the settings window opens on Windows, and that it needs no game.

The window is only useful if it really appears, and it is the one part of the project
that must work with the client closed - it is how the id and the whitelist get set in
the first place. This starts it, looks for its window by title, and closes it.

Read-only about the game: it never touches the client, and it says whether the client
happens to be running rather than requiring either answer.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\probe-config-gui.py
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WINDOW_TITLE = "DFBossReminder settings"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", default="",
                        help="test a built DFBossReminderConfig.exe instead of the source")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL

    # The check is that tkinter imports at all: a Python without it is a real
    # install, and the message should say so rather than "no window appeared".
    import importlib.util

    exe = args.exe
    if exe and not Path(exe).exists():
        print(f"FAIL: no file at {exe}")
        return 1
    if not exe and importlib.util.find_spec("tkinter") is None:
        print("FAIL: this Python has no tkinter, so the settings window cannot open")
        return 1

    command = [exe] if exe else [sys.executable, str(PROJECT_ROOT / "tools" / "dfboss_config_main.py")]
    print(f"starting: {' '.join(command)}")
    process = subprocess.Popen(command, cwd=str(PROJECT_ROOT))

    hwnd = 0
    deadline = time.time() + 25
    while time.time() < deadline and not hwnd:
        time.sleep(0.5)
        # c_void_p returns None for a NULL result, not 0.
        hwnd = int(user32.FindWindowW(None, WINDOW_TITLE) or 0)

    if not hwnd:
        process.terminate()
        print(f"FAIL: no window titled {WINDOW_TITLE!r} appeared")
        return 1

    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))  # noqa: B018
    visible = bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))
    print(f"found the settings window: hwnd={hex(hwnd)} visible={visible} "
          f"({rect.left},{rect.top})-({rect.right},{rect.bottom})")
    print(f"size: {rect.right - rect.left} x {rect.bottom - rect.top}")

    # It must work with the game shut, so this is reported, not required.
    # The probe itself always needs the package, whether it is testing the exe or the
    # source: the exe bundles its own copy, but this script runs under system Python.
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from dfbossreminder.services.window import find_game_window  # noqa: E402

    game = find_game_window()
    print(f"game running: {'yes' if game else 'no'} "
          f"(the settings window must open either way)")

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()

    if not visible:
        print("PROBLEMS:\n  - the window exists but is not visible")
        return 1
    print("PASS: the settings window opens, with no game required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
