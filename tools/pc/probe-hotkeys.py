"""Find which global hotkeys are free on this machine.

The in-game whitelist toggle is a global hotkey, and a hotkey another application
already holds cannot be registered - it fails, and the toggle simply does not exist
for the player. F8 turned out to be taken on the game PC, which is why the toggle key
is a setting rather than a constant.

This registers each candidate to its own thread, reports whether it worked, and
releases every one it took. It is read-only about the game: no window, no input.

It must run inside the interactive desktop session, because hotkeys belong to a
session - a session-0 answer says nothing about the session the player is in.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\probe-hotkeys.py
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes

MOD_NOREPEAT = 0x4000
CANDIDATES = [f"F{n}" for n in range(1, 13)] + ["INSERT", "HOME", "END", "PAUSE"]
VK = {f"F{n}": 0x6F + n for n in range(1, 13)}
VK.update({"INSERT": 0x2D, "HOME": 0x24, "END": 0x23, "PAUSE": 0x13})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefer", default="F8",
                        help="the key the tool currently uses, called out in the summary")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL

    free: list[str] = []
    taken: list[str] = []
    for index, name in enumerate(CANDIDATES):
        # A NULL window registers the hotkey to this thread, which collides with another
        # application's global hotkey exactly as the real overlay would.
        if user32.RegisterHotKey(None, index + 1, MOD_NOREPEAT, VK[name]):
            free.append(name)
            user32.UnregisterHotKey(None, index + 1)
        else:
            taken.append(name)

    print(f"free:  {' '.join(free) if free else '(none)'}")
    print(f"taken: {' '.join(taken) if taken else '(none)'}")
    print()
    if args.prefer.upper() in free:
        print(f"PASS: {args.prefer} is free, so the toggle hotkey works as configured")
        return 0
    print(f"{args.prefer} is NOT available. Set a free one, e.g.:")
    if free:
        print(f'  dfboss --hotkey {free[0]}')
        print('  (or the same field in the settings window)')
    else:
        print("  every candidate is taken; another application is holding the function keys")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
