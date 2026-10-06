"""Prove the tick boxes work on the live client: hit-testing, a click, and the next cycle.

The box column is three claims that a Mac cannot check. This probe drives the real code on
the game PC, in the interactive desktop session, and answers each one with a measurement:

1. **a click on a box reaches the box** - ``WindowFromPoint`` at the centre of a box must
   resolve to the box column's own window, because that is the call Windows uses to decide
   where a click goes;
2. **a click anywhere else still reaches the game** - ``WindowFromPoint`` over the readout's
   text must resolve to the client, and so must a point inside the box column that is not on
   a box. The boxes must not cost the click-through property the readout has always had;
3. **the tick hides the whole spawn, and only until the next cycle** - a real
   ``WM_LBUTTONDOWN`` is posted to the column (the same message a mouse produces, going
   through the queue and the loop's pump rather than straight into the window procedure),
   and then the feed is rolled over to the *next cycle* and the loop's own fetch brings the
   boss back.

The payload comes from a fake client rather than the live boss map, so the probe can drive a
boss through a cycle boundary without waiting an hour for one, and so its result does not
depend on what happens to be spawning.

The presenter is created **on the loop's thread**, as ``OverlayController`` does it in the
real program, and for the same reason: a window belongs to the thread that made it, and a
window call from anywhere else blocks for ever, because that thread only pumps inside its
own sleep slices.
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
from dfbossreminder.services import window as window_module  # noqa: E402
from dfbossreminder.services.window import find_game_window  # noqa: E402

WM_LBUTTONDOWN = 0x0201
MK_LBUTTON = 0x0001
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

CYCLE_ONE = 1791259201
CYCLE_TWO = CYCLE_ONE + 3600          # the next hour: the same bosses, respawned


def bossmap(start: int, player: tuple[int, int]) -> dict:
    """Two spawns: one with two places (the player's own example), one with a single place.

    ``6 x Bandits`` is at the player's block and the one east of it - two rows from one
    event, the case the player described. ``2 x Bandits`` is a separate event with its own
    single place, and it must survive the tick.
    """
    x, y = player
    return {
        "19": {"game_id": "19", "special_enemy_type": "6 x Bandits",
               "special_enemy_amount": "6", "boss_num": "1", "event_type": "",
               "start_time": str(start), "end_time": str(start + 3600),
               "locations": [[str(x), str(y)], [str(x + 1), str(y)]]},
        "6": {"game_id": "6", "special_enemy_type": "2 x Bandits",
              "special_enemy_amount": "2", "boss_num": "2", "event_type": "",
              "start_time": str(start), "end_time": str(start + 3600),
              "locations": [[str(x), str(y - 1)]]},
    }


class FakeClient:
    """The boss map, as the probe wants it: two spawns, three rows, a cycle to roll over."""

    def __init__(self, player: tuple[int, int]) -> None:
        self.player = player
        self.cycle = CYCLE_ONE

    def bossmap(self) -> dict:
        return bossmap(self.cycle, self.player)

    def profile(self, user_id: str) -> dict:  # noqa: ARG002
        return {"gpscoords": [str(self.player[0]), str(self.player[1])],
                "override": {"account_name": "probe"}}


UNDERLAY_AT = (60, 60)
UNDERLAY_SIZE = (560, 320)


def make_underlay(user32) -> int:
    """A plain, visible window to stand in for the client when the game is not running.

    The question this probe answers about click-through is "does a click land on the window
    underneath", and that question is the same whether the window underneath is the game or
    this. It is deliberately small, plain and short-lived: it is a probe window on somebody's
    desktop, not a feature.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    @WNDPROC
    def _proc(hwnd, message, wparam, lparam):  # noqa: ANN001, ANN202
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    class _WNDCLASS(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    klass = _WNDCLASS()
    klass.lpfnWndProc = _proc
    klass.hbrBackground = 16                                     # a plain grey brush
    klass.lpszClassName = "DFBossProbeUnderlay"
    if not user32.RegisterClassW(ctypes.byref(klass)):
        raise OSError(f"RegisterClassW failed: {ctypes.get_last_error()}")
    fake = getattr(make_underlay, "_proc_ref", None)
    make_underlay._proc_ref = _proc                              # keep it alive         # noqa: SLF001
    del fake
    hwnd = user32.CreateWindowExW(0, "DFBossProbeUnderlay", "DFTools probe: stands in for "
                                  "the game window", 0x80000000 | 0x10000000,  # popup|visible
                                  UNDERLAY_AT[0], UNDERLAY_AT[1], UNDERLAY_SIZE[0],
                                  UNDERLAY_SIZE[1], None, None, None, None)
    if not hwnd:
        raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
    return int(hwnd)


def bind():  # noqa: ANN202 - ctypes handles
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassW.restype = wintypes.WORD
    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                       wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_long
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    return user32


def describe_window(user32, hwnd: int) -> str:
    if not hwnd:
        return "(none)"
    klass = ctypes.create_unicode_buffer(128)
    title = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), klass, 128)
    user32.GetWindowTextW(wintypes.HWND(hwnd), title, 256)
    return f"{klass.value!r} {title.value[:40]!r}"


def hit(user32, point: tuple[int, int]) -> int:
    return int(user32.WindowFromPoint(wintypes.POINT(*point)))


def wait_until(predicate, seconds: float = 8.0, step: float = 0.1) -> bool:  # noqa: ANN001
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False


def main() -> int:  # noqa: C901 - a probe reads better as one straight sequence
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", default="", help="directory for the before/after BMPs")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    problems: list[str] = []
    user32 = bind()
    underlay = 0
    game = find_game_window()
    if game is None:
        # No client window to anchor to, and the presenter refuses to open without one -
        # which is the product's own rule (no game, no overlay), not something to work
        # around by weakening it. So a plain window stands in: same question, controlled
        # answer. What it cannot prove is the in-game anchor, which the other probes and the
        # settings-window audit cover with the client up.
        underlay = make_underlay(user32)
        game = window_module.measure_window(user32, underlay)
        app.find_game_window = lambda: game          # what the presenter measures
        print("the Dead Frontier client is not running: standing a plain window in for it "
              f"({UNDERLAY_SIZE[0]}x{UNDERLAY_SIZE[1]} at {UNDERLAY_AT}, gone at the end)")
    print(f"anchored to: {game.client.as_dict()}")

    settings = parse_settings({
        "user_id": "14008279", "presentation": "overlay", "anchor": "top-left",
        "radius_blocks": 200, "poll_seconds": 2.0, "font_size": 12, "width": 360,
    })
    client = FakeClient((1057, 1017))
    stop = threading.Event()
    state: dict = {}

    def loop() -> None:
        """The real arrangement: the loop's own thread creates both windows."""
        presenter = app.OverlayPresenter(
            settings, use_client_area=True,
            font_cache=Path.home() / ".dfbossreminder" / "game-font.ttf",
            log=lambda message: print(f"    [presenter] {message}"))
        watch = app.Watch(settings, client, presenter,
                          Path("/nonexistent/probe.json"), log=lambda *_a: None)
        state["presenter"], state["watch"] = presenter, watch
        state["ready"].set()
        watch.run(stop=stop)                # closes both windows on the way out

    state["ready"] = threading.Event()
    thread = threading.Thread(target=loop, name="probe-loop", daemon=True)
    thread.start()
    if not state["ready"].wait(timeout=20):
        print("FAIL: the readout's thread never came up (no game window?)")
        return 1
    presenter, watch = state["presenter"], state["watch"]

    if not wait_until(lambda: len(presenter.overlay.rows) == 3):
        stop.set()
        thread.join(timeout=10)
        print("FAIL: the readout never drew the three rows the payload describes; drew "
              f"{[row.text for row in presenter.overlay.rows]}")
        return 1
    time.sleep(0.8)
    readout, column = int(presenter.overlay.hwnd), int(presenter.boxes.hwnd)
    readout_style = int(user32.GetWindowLongW(wintypes.HWND(readout), GWL_EXSTYLE))
    column_style = int(user32.GetWindowLongW(wintypes.HWND(column), GWL_EXSTYLE))
    print(f"after the first draw: {len(presenter.overlay.rows)} rows, "
          f"{len(presenter.boxes.boxes)} boxes")
    for row in presenter.overlay.rows:
        print(f"    {row.text!r}")
    print(f"readout hwnd={hex(readout)} WS_EX_TRANSPARENT="
          f"{bool(readout_style & WS_EX_TRANSPARENT)} (must stay True)")
    print(f"column  hwnd={hex(column)} WS_EX_TRANSPARENT="
          f"{bool(column_style & WS_EX_TRANSPARENT)} WS_EX_NOACTIVATE="
          f"{bool(column_style & WS_EX_NOACTIVATE)} (must be False / True)")

    boxes = presenter.boxes.boxes
    first = boxes[0]
    box_point = (presenter.boxes.left + (first.rect[0] + first.rect[2]) // 2,
                 presenter.boxes.top + (first.rect[1] + first.rect[3]) // 2)
    gap_point = (presenter.boxes.left + 1, presenter.boxes.top + first.rect[3] + 3)
    text_point = (presenter.overlay.left + 30, presenter.overlay.top + first.rect[1] + 4)

    points = {"box": box_point, "column gap": gap_point, "readout text": text_point}
    hits = {name: hit(user32, point) for name, point in points.items()}
    for name, point in points.items():
        print(f"  WindowFromPoint at the {name} {point} -> "
              f"{describe_window(user32, hits[name])}")

    if hits["box"] != column:
        problems.append("WindowFromPoint on a box did not resolve to the box column, so a "
                        "click there would not reach the tick")
    for name in ("column gap", "readout text"):
        if hits[name] in (readout, column):
            problems.append(f"WindowFromPoint at the {name} resolved to our own window: the "
                            f"readout would swallow a click that used to reach the game")
        elif hits[name] != int(game.hwnd):
            problems.append(f"WindowFromPoint at the {name} resolved to "
                            f"{describe_window(user32, hits[name])}, not the window "
                            f"underneath")
    if not readout_style & WS_EX_TRANSPARENT:
        problems.append("the readout lost WS_EX_TRANSPARENT")
    if column_style & WS_EX_TRANSPARENT:
        problems.append("the box column has WS_EX_TRANSPARENT, so it can never be clicked")
    if not column_style & WS_EX_NOACTIVATE:
        problems.append("the box column may take focus from the game")

    evidence = Path(args.evidence) if args.evidence else None
    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        presenter.dump(str(evidence / "readout-before.bmp"),
                       str(evidence / "boxes-before.bmp"))
        print(f"surfaces written to {evidence}")

    # A real click, as Windows delivers it: posted to the queue, dispatched by the loop's
    # pump on the loop's thread, handled by the window procedure.
    x, y = box_point[0] - presenter.boxes.left, box_point[1] - presenter.boxes.top
    print(f"posting WM_LBUTTONDOWN to the box at {box_point} (client {x},{y})")
    if not user32.PostMessageW(wintypes.HWND(column), WM_LBUTTONDOWN, MK_LBUTTON,
                               (y << 16) | (x & 0xFFFF)):
        problems.append("PostMessageW failed")

    if not wait_until(lambda: len(presenter.overlay.rows) == 1, seconds=5):
        problems.append(f"the tick did not remove the spawn's rows: "
                        f"{[row.text for row in presenter.overlay.rows]}")
    time.sleep(0.6)
    remaining = [row.text for row in presenter.overlay.rows]
    print(f"after the tick: {len(remaining)} row(s) - {remaining}")
    print(f"dismissed: {list(watch.dismissed.labels.values())}")
    if len(watch.dismissed) != 1:
        problems.append(f"expected exactly one dismissed spawn, got {len(watch.dismissed)}")
    if any("6 x Bandits" in text for text in remaining):
        problems.append("the ticked boss is still on screen")
    if not any("2 x Bandits" in text for text in remaining):
        problems.append("the tick removed a boss the player did not point at")
    if evidence:
        presenter.dump(str(evidence / "readout-after.bmp"),
                       str(evidence / "boxes-after.bmp"))

    # The next cycle: the loop fetches by itself (poll_seconds=2) and the payload's start
    # time has moved on, so this is a different spawn of the same boss at the same place -
    # which is exactly the case the player's third requirement is about.
    print(f"rolling the feed over to the next cycle (start {CYCLE_TWO})")
    client.cycle = CYCLE_TWO
    if not wait_until(lambda: len(presenter.overlay.rows) == 3, seconds=10):
        problems.append(f"the next cycle did not bring the boss back: "
                        f"{[row.text for row in presenter.overlay.rows]}")
    else:
        print(f"next cycle: {len(presenter.overlay.rows)} rows again - "
              f"{[row.text for row in presenter.overlay.rows]}")
    if len(watch.dismissed):
        problems.append("a dismissal survived into the next cycle")
    if evidence:
        presenter.dump(str(evidence / "readout-next-cycle.bmp"),
                       str(evidence / "boxes-next-cycle.bmp"))

    stop.set()
    thread.join(timeout=15)
    time.sleep(0.5)
    alive = [name for name, handle in (("readout", readout), ("column", column))
             if user32.IsWindow(wintypes.HWND(handle))]
    print(f"after the loop stopped: windows still alive = {alive or 'none'}")
    if alive:
        problems.append(f"stopping the readout left its {', '.join(alive)} window behind")
    if underlay:
        user32.DestroyWindow(wintypes.HWND(underlay))
        user32.UnregisterClassW("DFBossProbeUnderlay", None)
        print("the stand-in window is gone")

    print()
    if problems:
        print("PROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("PASS: a box is clickable, everything else still clicks through, one tick hides the "
          "whole spawn, and the next cycle brings it back")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
