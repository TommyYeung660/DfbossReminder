"""Prove the automatic re-anchor on the live client: move the window, wait, watch it follow.

The player asked for this on 2026-10-07: "每30秒自動做一次overlay 位置校正, overlay 校正按鈕保留".
The feature it reinstates was deleted on 2026-09-23 for moving the list under the player's eyes,
so the three things this probe measures are exactly the three that make it acceptable:

1. **the readout follows a moved client by itself** - no button, no key, within the interval;
2. **it does not fight the player**: a nudge stays applied across an automatic pass (the button
   clears it, the timer must not - that was the old complaint);
3. **it stays silent when nothing moved**: no log line, no redraw of the position, so a run with
   a stationary client looks exactly like a run before the feature existed.

The presenter is created **on the loop's thread**, as ``OverlayController`` does in the real
program, because a window belongs to the thread that made it.

Usage (game PC, interactive session, client running):
    py -3 tools\\pc\\probe-auto-align.py
    py -3 tools\\pc\\probe-auto-align.py --evidence tools\\pc\\evidence\\auto-align
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dfbossreminder import app  # noqa: E402
from dfbossreminder.domain.settings import parse_settings  # noqa: E402
from dfbossreminder.services.window import find_game_window  # noqa: E402

SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def bind():  # noqa: ANN202 - ctypes handles
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    return user32


def window_rect(user32, hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))  # noqa: B018
    return (rect.left, rect.top, rect.right, rect.bottom)


def move_window(user32, hwnd: int, left: int, top: int) -> None:
    was = window_rect(user32, hwnd)
    user32.SetWindowPos(wintypes.HWND(hwnd), None, int(left), int(top),
                        was[2] - was[0], was[3] - was[1],
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def readout_rect(user32, prefix: str = "DFBossReminderOverlay"):  # noqa: ANN201
    """The text window's rectangle, found by its class name."""
    found: list[tuple[int, int, int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):  # noqa: ANN001, ANN202
        buffer = ctypes.create_unicode_buffer(128)
        user32.GetClassNameW(wintypes.HWND(hwnd), buffer, 128)
        if buffer.value.startswith(prefix) and user32.IsWindowVisible(wintypes.HWND(hwnd)):
            found.append(window_rect(user32, int(hwnd)))
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def expected_position(offset: int = 14) -> tuple[int, int] | None:
    """Where the readout belongs right now, from the client as it is *now*.

    Measuring rather than assuming: this probe moves the game window, and a client that also
    moves itself (Unity apps do re-centre) would make "it followed by the delta I asked for"
    fail for a reason that has nothing to do with the feature.
    """
    window = find_game_window()
    if window is None:
        return None
    return (window.client.left + offset, window.client.top + offset)


def wait_until(predicate, seconds: float, step: float = 0.5) -> bool:  # noqa: ANN001
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def main() -> int:  # noqa: C901 - a probe reads better as one straight sequence
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="", help="directory for the surface dumps")
    parser.add_argument("--wait", type=float, default=45.0,
                        help="how long to wait for one automatic pass (interval + slack)")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    problems: list[str] = []
    user32 = bind()
    game = find_game_window()
    if game is None:
        print("the Dead Frontier client is not running: start it and run this again")
        return 1
    print(f"game window: {game.client.as_dict()}")

    interval = parse_settings({}).auto_align_seconds
    print(f"the shipped default interval is {interval:.0f}s")
    if interval != 30.0:
        problems.append(f"the default interval is {interval}, and the player asked for 30")

    settings = parse_settings({
        "user_id": "14008279", "presentation": "overlay", "anchor": "top-left",
        "radius_blocks": 200, "poll_seconds": 5.0, "font_size": 12, "width": 360,
        "auto_align_seconds": args.wait / 1.5 if args.wait else 30.0,
    })
    stop = threading.Event()
    state: dict = {"ready": threading.Event(), "moves": []}

    def loop() -> None:
        presenter = app.OverlayPresenter(
            settings, use_client_area=True,
            font_cache=Path.home() / ".dfbossreminder" / "game-font.ttf",
            log=lambda message: print(f"    [presenter] {message}"))
        # Record what the loop actually asks for, so "no move" can be told from "a move that
        # happened to be a no-op".
        original = presenter.reposition

        def reposition(settings_=None, nudge=None, window=None):  # noqa: ANN001
            note = original(settings_, nudge, window)
            state["moves"].append((nudge, note))
            return note

        presenter.reposition = reposition
        watch = app.Watch(settings, _client(), presenter,
                          Path("/nonexistent/probe.json"), log=lambda *_a: None)
        state["presenter"], state["watch"] = presenter, watch
        state["ready"].set()
        watch.run(stop=stop)

    class _client:
        """A boss map with one boss on the player, so the readout has a row to draw."""

        def bossmap(self) -> dict:
            return {"1": {"game_id": "1", "special_enemy_type": "1 x Probe Boss",
                          "special_enemy_amount": "1", "boss_num": "1", "event_type": "",
                          "start_time": "0", "end_time": str(time.time() + 3600),
                          "locations": [["1057", "1017"]]}}

        def profile(self, user_id: str) -> dict:  # noqa: ARG002
            return {"gpscoords": ["1057", "1017"], "override": {"account_name": "probe"}}

    thread = threading.Thread(target=loop, name="probe-loop", daemon=True)
    thread.start()
    if not state["ready"].wait(timeout=20):
        print("FAIL: the readout's thread never came up (no game window?)")
        return 1
    presenter, watch = state["presenter"], state["watch"]

    if not wait_until(lambda: readout_rect(user32) is not None, seconds=10):
        stop.set()
        thread.join(timeout=10)
        print("FAIL: the readout window never appeared")
        return 1
    time.sleep(1.0)
    before = readout_rect(user32)
    print(f"placed at {before}")

    # 1. Move the client and touch nothing. The readout has to follow on its own.
    was = window_rect(user32, game.hwnd)
    delta = (-70, -50)
    print(f"moving the client by {delta} and waiting up to {args.wait:.0f}s for the timer")
    move_window(user32, game.hwnd, was[0] + delta[0], was[1] + delta[1])
    time.sleep(1.0)
    client_now = find_game_window()
    print(f"the client is now reported at "
          f"{client_now.client.as_dict() if client_now else 'nowhere'}")

    def arrived() -> bool:
        where, want = readout_rect(user32), expected_position()
        return where is not None and want is not None and where[:2] == want

    followed = wait_until(arrived, seconds=args.wait)
    after = readout_rect(user32)
    print(f"after the wait: readout {after}, belongs at {expected_position()}")
    if not followed:
        problems.append(f"the readout did not follow the moved client by itself: {after} "
                        f"vs {expected_position()}")

    # 2. A nudge must survive an automatic pass. Pressing one here goes through the same queued
    #    request the settings window's arrows use.
    nudge = (5, 5)
    print(f"applying a {nudge} nudge and moving the client again")
    watch.request_settings(settings, nudge)
    time.sleep(0.8)
    placed_with_nudge = readout_rect(user32)
    wanted = expected_position()
    print(f"with the nudge: readout {placed_with_nudge}, without it {wanted}")
    if wanted is None or placed_with_nudge[:2] == wanted:
        problems.append("the nudge did not move the readout, so nothing can be judged about "
                        "it surviving the timer")

    state["moves"].clear()               # only the automatic passes from here on
    was = window_rect(user32, game.hwnd)
    move_window(user32, game.hwnd, was[0] + 60, was[1] + 40)
    time.sleep(1.0)
    client_now = find_game_window()
    print(f"the client is now at "
          f"{client_now.client.as_dict() if client_now else 'nowhere'}")
    # How far the nudge put the readout from where the configuration alone would put it. The
    # nudge is an offset, so after an automatic pass the readout must be the configured
    # position again *plus this*, whatever the client did in the meantime.
    off = (placed_with_nudge[0] - wanted[0], placed_with_nudge[1] - wanted[1])
    # The nudge is an offset from the configured position, so after the automatic pass the
    # readout must be the configured position again plus that same offset.
    def kept_nudge() -> bool:
        where, want = readout_rect(user32), expected_position()
        return (where is not None and want is not None
                and where[:2] == (want[0] + off[0], want[1] + off[1]))

    if not wait_until(kept_nudge, seconds=args.wait):
        problems.append(f"the automatic pass did not keep the nudge: "
                        f"{readout_rect(user32)} vs {expected_position()} + {off}")
    kept = readout_rect(user32)
    print(f"after the automatic pass: {kept} (plain position would be {expected_position()}, "
          f"the nudge is {off})")
    automatic = [nudge_seen for nudge_seen, _note in state["moves"]]
    if any(nudge_seen is not None for nudge_seen in automatic):
        problems.append(f"an automatic pass asked for a nudge of {automatic}, and the timer "
                        f"must never touch the player's adjustment")
    if not automatic:
        problems.append("no automatic pass ran during the second move")

    # 3. Nothing moved since the last pass, so the next one must be a no-op and silent.
    state["moves"].clear()
    time.sleep(max(2.0, settings.auto_align_seconds + 3))
    notes = [note for _nudge, note in state["moves"]]
    print(f"with the client still: {len(state['moves'])} automatic pass(es), notes {notes}")
    if not state["moves"]:
        problems.append("no automatic pass happened while waiting, so nothing was measured")
    if any(note for note in notes):
        problems.append(f"an automatic pass claimed to move the readout while the client had "
                        f"not moved: {notes}")

    # Put the client back, let one more pass settle it, then stop.
    move_window(user32, game.hwnd, was[0], was[1])
    wait_until(arrived, seconds=args.wait)
    print(f"client put back at {was}; readout at {readout_rect(user32)}")

    evidence = Path(args.evidence) if args.evidence else None
    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        presenter.dump(str(evidence / "readout.bmp"), str(evidence / "boxes.bmp"))
        print(f"surfaces written to {evidence}")

    stop.set()
    thread.join(timeout=15)
    print("loop stopped, windows closed")

    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: the readout re-anchors itself on the timer, keeps the player's nudge, and says "
          "nothing when the client has not moved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
