"""Prove the client-rectangle measurement against real windows on this machine.

The overlay's in-game mode anchors itself to the game window's client rectangle, so
the arithmetic that turns ``GetClientRect`` + ``ClientToScreen`` into a screen
rectangle has to be right on *this* display at *this* DPI scaling. That cannot be
checked from the development Mac, and it cannot be checked over SSH either: an SSH
session is session 0, which cannot see the interactive session's windows at all, so
the window list would be empty and prove nothing. This probe therefore runs through
the interactive scheduled task.

It reads only: window classes, titles, rectangles and the process id. It sends no
input and creates no window.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\probe-window.py
    py -3 tools\\pc\\probe-window.py --list 20
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dfbossreminder.services import window as window_module  # noqa: E402
from dfbossreminder.services.window import find_game_window, measure_window  # noqa: E402

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000


def bind():  # noqa: ANN202 - ctypes handles
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    return user32


def describe(user32, hwnd: int) -> dict:
    """One window, as the information the anchoring decision uses."""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, 256)
    title = buffer.value
    klass = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), klass, 256)
    style = user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE)
    measured = measure_window(user32, hwnd)
    return {
        "hwnd": hex(hwnd),
        "title": title,
        "class": klass.value,
        "decorated": bool(style & (WS_CAPTION | WS_THICKFRAME)),
        "client": measured.client.as_dict() if measured else None,
        "pid": measured.pid if measured else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", type=int, default=12, help="how many visible windows to report")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    user32 = bind()

    screen = window_module.screen_rect(user32)
    print(f"screen: {screen.as_dict() if screen else None}")
    print()

    # The question the in-game mode depends on.
    game = find_game_window()
    if game is None:
        print("game window: NOT FOUND (is DeadFrontier.exe running?)")
        print("  -> --presentation overlay will fall back to the screen and say so")
    else:
        print(f"game window: hwnd={hex(game.hwnd)} pid={game.pid} title={game.title!r}")
        print(f"  client in screen coordinates: {game.client.as_dict()}")
        print(f"  exclusive_fullscreen (heuristic): {game.exclusive_fullscreen}")
        print(f"  {game.presentation_note}")
    print()

    rows: list[dict] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _lparam):  # noqa: ANN001, ANN202
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        info = describe(user32, hwnd)
        # Decorated windows are the interesting ones: a client rectangle that is
        # inset from the window's own rectangle is what proves the measurement is
        # taking the client area and not the frame.
        if info["client"] and (info["decorated"] or info["title"]):
            rows.append(info)
        return True

    user32.EnumWindows(collect, 0)

    decorated = [row for row in rows if row["decorated"]]
    print(f"visible windows: {len(rows)} ({len(decorated)} decorated)")
    print(f"{'class':<24}{'client (screen)':<34}{'title'}")
    shown = 0
    for row in rows:
        if not row["decorated"]:
            continue
        client = row["client"]
        where = f"({client['left']},{client['top']}) {client['width']}x{client['height']}"
        print(f"{row['class'][:23]:<24}{where:<34}{row['title'][:36]}")
        shown += 1
        if shown >= args.list:
            break

    print()
    problems = []
    if not decorated:
        problems.append("no decorated window found: session 0 has no visible windows, "
                        "so this probe must run through the interactive task")
    for row in decorated:
        client = row["client"]
        # Windows places a minimized window at the -32000 sentinel. That is not a
        # measurement problem, and neither is a window hanging a few pixels off an
        # edge, so the test is whether the rectangle intersects the screen at all -
        # which is the failure that would actually matter (every window measured at
        # 0,0, or off in the weeds).
        if client["left"] <= -30000 or client["top"] <= -30000 or screen is None:
            continue
        right = client["left"] + client["width"]
        bottom = client["top"] + client["height"]
        if right <= 0 or bottom <= 0 or client["left"] >= screen.width or client["top"] >= screen.height:
            problems.append(f"{row['title'][:20]!r} client rectangle does not intersect the "
                            f"screen: ({client['left']},{client['top']}) "
                            f"{client['width']}x{client['height']}")

    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("client rectangles are on-screen and plausible: the measurement works here")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
