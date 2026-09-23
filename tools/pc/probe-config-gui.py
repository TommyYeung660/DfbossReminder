"""Prove the settings window opens on Windows, and that it needs no game.

The window is only useful if it really appears, and it is the one part of the project
that must work with the client closed - it is how the id and the whitelist get set in
the first place. This starts it, looks for its window by title, photographs it, and
closes it.

The title is Chinese, like the rest of the window, and it is how the window is found -
so the probe fails loudly if the title and the window ever disagree rather than silently
finding nothing.

Read-only about the game: it never touches the client, and it says whether the client
happens to be running rather than requiring either answer.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\probe-config-gui.py
    py -3 tools\\pc\\probe-config-gui.py --exe "%USERPROFILE%\\Desktop\\DFBossReminderConfig.exe"
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
WINDOW_TITLE = "DFBossReminder 設定"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", default="",
                        help="test a built DFBossReminderConfig.exe instead of the source")
    parser.add_argument("--no-shot", action="store_true",
                        help="skip the screenshot (the default is to take one)")
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
    # Its output is Chinese: the code page the console happens to have would make the
    # error path unreadable exactly when it is needed. The exit code and whether the
    # window appeared are what the probe checks either way.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):            # pragma: no cover - a redirected stream
        pass
    process = subprocess.Popen(command, cwd=str(PROJECT_ROOT))

    hwnd = 0
    deadline = time.time() + 25
    while time.time() < deadline and not hwnd:
        time.sleep(0.5)
        # c_void_p returns None for a NULL result, not 0.
        hwnd = int(user32.FindWindowW(None, WINDOW_TITLE) or 0)

    if not hwnd:
        stop(process)
        print(f"FAIL: no window titled {WINDOW_TITLE!r} appeared")
        return 1

    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))  # noqa: B018
    visible = bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))
    print(f"found the settings window: hwnd={hex(hwnd)} visible={visible} "
          f"({rect.left},{rect.top})-({rect.right},{rect.bottom})")
    print(f"size: {rect.right - rect.left} x {rect.bottom - rect.top}")

    # A picture, because "the labels in the source are Chinese" says nothing about whether
    # Windows draws them or puts up a row of boxes. PrintWindow, never a screen crop and
    # never an activation: the player may be in the middle of a fight, and stealing the
    # focus to take a screenshot would be worse than having no screenshot.
    if not args.no_shot:
        # The window is mapped as soon as the root exists, which is *before* the form is
        # built: a capture taken the moment the title appears can photograph a bottom that
        # has not been painted yet. Two seconds of settle, because a screenshot of a
        # half-built window is worse than none - it looks like a layout bug.
        time.sleep(2.0)
        shot = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "pc" / "capture-window.py"),
             "--title", WINDOW_TITLE, "--label", "config-gui"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(PROJECT_ROOT))
        print((shot.stdout or shot.stderr).strip())
        if shot.returncode != 0:
            print("WARNING: the window could not be photographed")

    # It must work with the game shut, so this is reported, not required.
    # The probe itself always needs the package, whether it is testing the exe or the
    # source: the exe bundles its own copy, but this script runs under system Python.
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from dfbossreminder.services.window import find_game_window  # noqa: E402

    game = find_game_window()
    print(f"game running: {'yes' if game else 'no'} "
          f"(the settings window must open either way)")

    stop(process)

    if not visible:
        print("PROBLEMS:\n  - the window exists but is not visible")
        return 1
    print("PASS: the settings window opens, with no game required")
    return 0


def stop(process: subprocess.Popen) -> None:
    """Kill the settings window and everything it started.

    The built exe is a one-file PyInstaller bundle, which is a parent process that
    unpacks and launches the real one. Terminating the parent leaves the child - so the
    window stayed open on the player's desktop after every probe run, and the next run
    then found two windows. The tree has to be killed, not the process that was started.
    """
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:                # pragma: no cover - already killed
        process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
