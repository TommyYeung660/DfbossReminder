"""Prove the overlay is click-through and never takes focus, on the live client.

Two claims the in-game mode rests on cannot be checked from the development Mac or
over SSH:

* a click over the readout reaches the game instead of being swallowed by the
  overlay, and
* the overlay does not take focus from the client.

The first has a definitive programmatic answer. Windows skips a ``WS_EX_TRANSPARENT``
window when it hit-tests the mouse, so ``WindowFromPoint`` at a point inside the
overlay must resolve to whatever is *underneath* - the game - and never to the
overlay itself. The style bit is read back too, because that is the mechanism the
result depends on. The second is answered by comparing the foreground window before
and after the overlay appears.

This runs in the interactive desktop session (an SSH session's windows are invisible
to a hit test). It creates the overlay it is testing, and it sends no input.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\probe-clickthrough.py
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
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dfbossreminder.services.window import find_game_window  # noqa: E402

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
OVERLAY_CLASS_PREFIX = "DFBossReminderOverlay"


def bind():  # noqa: ANN202 - ctypes handles
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    return user32


def find_overlay(user32) -> int | None:
    """The overlay's own window, found by its class name prefix."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):  # noqa: ANN001, ANN202
        buffer = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(wintypes.HWND(hwnd), buffer, 128)
        if buffer.value.startswith(OVERLAY_CLASS_PREFIX):
            found.append(int(hwnd))
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def title_of(user32, hwnd: int) -> str:
    """A short, useful name for whatever window a point resolves to."""
    if not hwnd:
        return "(none)"
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, 256)
    klass = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(wintypes.HWND(hwnd), klass, 128)
    return f"{klass.value!r} {buffer.value[:40]!r}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--presentation", default="overlay", choices=("overlay", "panel"))
    parser.add_argument("--anchor", default="top-left")
    parser.add_argument("--seconds", type=float, default=25.0)
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    user32 = bind()
    game = find_game_window()
    print(f"game window: {'none' if game is None else game.client.as_dict()}")

    before = int(user32.GetForegroundWindow())
    print(f"foreground before: {title_of(user32, before)}")

    command = [sys.executable, str(PROJECT_ROOT / "tools" / "dfboss_main.py"),
               "--presentation", args.presentation, "--anchor", args.anchor,
               "--seconds", str(args.seconds)]
    print(f"starting: {' '.join(command)}")
    process = subprocess.Popen(command, cwd=str(PROJECT_ROOT),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    hwnd = None
    deadline = time.time() + 20
    while time.time() < deadline and hwnd is None:
        time.sleep(0.5)
        hwnd = find_overlay(user32)
    if hwnd is None:
        process.terminate()
        print("FAIL: the overlay window never appeared")
        return 1

    # Give it a frame to draw and settle.
    time.sleep(2.5)

    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
    visible = bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE)
    print(f"overlay hwnd={hex(hwnd)} visible={visible} "
          f"rect=({rect.left},{rect.top})-({rect.right},{rect.bottom})")
    print(f"overlay ex-style: WS_EX_TRANSPARENT={bool(style & WS_EX_TRANSPARENT)} "
          f"WS_EX_NOACTIVATE={bool(style & WS_EX_NOACTIVATE)}")

    # A point well inside the overlay's rectangle.
    point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    hit = int(user32.WindowFromPoint(point))
    print(f"WindowFromPoint at the overlay's centre ({point.x},{point.y}) -> {title_of(user32, hit)}")

    after = int(user32.GetForegroundWindow())
    print(f"foreground after: {title_of(user32, after)}")

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()

    problems = []
    if not visible:
        problems.append("the overlay is not visible")
    if not style & WS_EX_TRANSPARENT:
        problems.append("the overlay does not have WS_EX_TRANSPARENT, so it will swallow clicks")
    if not style & WS_EX_NOACTIVATE:
        problems.append("the overlay does not have WS_EX_NOACTIVATE, so it may steal focus")
    if hit == hwnd:
        problems.append("WindowFromPoint resolved to the overlay itself: clicks would be swallowed")
    if after != before:
        problems.append(f"the foreground window changed ({hex(before)} -> {hex(after)}): "
                        f"the overlay took focus")

    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: clicks pass through to the window underneath, and focus was not taken")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
