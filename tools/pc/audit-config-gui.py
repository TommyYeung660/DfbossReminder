"""Check the settings window's widgets without showing it to anybody.

The data half of the window (the form, the payload, the validation) is tested on the
development machine. The *widget* half can only be checked where a real window exists -
the game PC - and the first attempt at this got it wrong in a way worth writing down: a
pytest file that built the window to inspect it put a dozen settings windows on the
developer's screen while the suite ran. That is not a test, it is an interruption, and it
still proved nothing about Windows.

So this builds the window **withdrawn**, walks it, invokes the buttons that do not need a
game, and prints what it found. Nothing appears on screen, nothing needs the game, and the
answer is about the machine that matters.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\audit-config-gui.py
    py -3 tools\\pc\\audit-config-gui.py --live        (also start and stop the real overlay)
    py -3 tools\\pc\\audit-config-gui.py --settings C:\\path\\to\\settings.json
"""

from __future__ import annotations

import argparse
import io
import sys
import tkinter as tk
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dfbossreminder.domain.settings import parse_settings  # noqa: E402
from dfbossreminder.ui import config_gui  # noqa: E402

# What the window has to contain once the whitelist is gone and the styles, the start
# button and the position nudge are in. Each is checked by name, so a section that stops
# being built is a failure and not a shorter list.
REQUIRED_SECTIONS = ("帳號與範圍", "座標樣式", "顯示外觀", "顯示位置", "位置微調")
REQUIRED_BUTTONS = ("開始", "停止", "儲存", "重新載入", "關閉", "←", "→", "↑", "↓", "新增樣式")
FORBIDDEN = ("白名單", "新增座標", "remove", "choose")
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010


def walk(widget):  # noqa: ANN001, ANN201
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


def labels(widget) -> list[str]:  # noqa: ANN001
    """Every piece of text the window carries, sections and columns included."""
    found: list[str] = []
    for child in walk(widget):
        for option in ("text", "label"):
            try:
                value = child.cget(option)
            except tk.TclError:
                continue
            if isinstance(value, str) and value:
                found.append(value)
    return found


def find_button(widget, text: str):  # noqa: ANN001, ANN201
    for child in walk(widget):
        if child.winfo_class() in ("TButton", "Button") and child.cget("text") == text:
            return child
    return None


def move_window(hwnd: int, left: int, top: int) -> None:
    """Move a window without resizing it, leaving its z-order and activation alone."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))  # noqa: B018
    user32.SetWindowPos(wintypes.HWND(hwnd), None, int(left), int(top),
                        rect.right - rect.left, rect.bottom - rect.top,
                        SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)


def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    rect = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))  # noqa: B018
    return (rect.left, rect.top, rect.right, rect.bottom)


def overlay_windows() -> list[tuple[int, tuple[int, int, int, int]]]:
    """Every visible overlay window on this desktop, as (hwnd, rectangle).

    The class name is the overlay's own (``DFBossReminderOverlay<pid>_<n>``), so this
    counts readout windows and nothing else. It is what turns "停止 does nothing" and "a
    second overlay appeared" from things a person notices into things this reports - both
    of which were real, and neither of which any test could have seen.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    found: list[tuple[int, tuple[int, int, int, int]]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):  # noqa: ANN001, ANN202
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(wintypes.HWND(hwnd), buffer, 256)
        if buffer.value.startswith("DFBossReminderOverlay") and \
                user32.IsWindowVisible(wintypes.HWND(hwnd)):
            rect = wintypes.RECT()
            user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))  # noqa: B018
            found.append((int(hwnd), (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(visit, 0)
    return found


class RecordingController:
    """Stands in for app.OverlayController: records instead of starting anything."""

    def __init__(self) -> None:
        self.started: list = []
        self.stopped = 0
        self.nudges: list = []

    def running(self) -> bool:
        return False

    def start(self, settings):  # noqa: ANN001, ANN201
        self.started.append(settings)
        return True, "audit: start was called"

    def stop(self) -> str:
        self.stopped += 1
        return "audit: stop was called"

    def nudge(self, settings, direction, step):  # noqa: ANN001, ANN201
        from dataclasses import replace

        from dfbossreminder.ui.layout import nudged

        x, y = nudged(settings.anchor, settings.offset_x, settings.offset_y, direction, step)
        self.nudges.append((direction, step))
        return replace(settings, offset_x=x, offset_y=y), f"位移 {x}, {y}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default="",
                        help="settings file to open with; a temporary one by default")
    parser.add_argument("--rules", default="red=1015,999;1020,998|green=1057,1017:2",
                        help="style rules to build the table with, as --highlight takes them")
    parser.add_argument("--live", action="store_true",
                        help="with the real controller: press 開始, let the overlay come up, "
                             "nudge it, then press 停止")
    parser.add_argument("--seconds", type=float, default=8.0,
                        help="how long to leave the overlay up with --live")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this audit only runs on Windows (it is about the window there)", file=sys.stderr)
        return 1

    for stream in (sys.stdout, sys.stderr):
        try:
            # Line-buffered on purpose: a run that hangs with its output in a buffer tells
            # you nothing, and this tool is exactly the kind that gets run to see where it
            # stops.
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):        # pragma: no cover
            pass

    settings = parse_settings({"user_id": "14008279", "radius_blocks": 5,
                               "highlights": args.rules, "anchor": "below-minimap"})
    path = Path(args.settings) if args.settings else Path("audit-settings.json")
    controller = RecordingController()
    captured = io.StringIO()

    if args.live:
        # The real controller, so this is the merged program's own path: the settings
        # window's 開始 opening the overlay, in this process, and 停止 taking it down.
        from dfbossreminder.app import OverlayController  # noqa: PLC0415

        controller = OverlayController(path, log=captured.write)

    problems: list[str] = []
    state: dict = {}
    original = tk.Tk.mainloop

    def one_pass(window, *_a, **_k) -> None:        # noqa: ANN001, ANN002, ANN003
        # Everything worth checking happens before the loop. The window is already
        # withdrawn, so this never appears on the desktop.
        window.update_idletasks()
        state["visible"] = bool(window.winfo_viewable())
        state["texts"] = labels(window)
        state["root"] = window
        raise StopIteration

    tk.Tk.mainloop = one_pass
    try:
        config_gui.run_config(path, load=lambda: settings, save=lambda value: None,
                              controller=controller, visible=False, log=captured.write)
    except StopIteration:
        pass
    finally:
        tk.Tk.mainloop = original

    if not state:
        print("PROBLEM: the window was never built")
        return 1
    texts = state["texts"]
    joined = " | ".join(texts)
    root = state["root"]
    print(f"the window was built withdrawn; viewable={state['visible']}")
    recorded = len(getattr(controller, "started", []))
    print(f"{len(texts)} labels, {recorded} starts recorded so far")

    for section in REQUIRED_SECTIONS:
        if section not in joined:
            problems.append(f"no section titled {section!r}")
    for text in REQUIRED_BUTTONS:
        if find_button(root, text) is None:
            problems.append(f"no button labelled {text!r}")
    for text in FORBIDDEN:
        if text in joined:
            problems.append(f"{text!r} is still in the window")

    # The table renders one row per rule: a widget-key mistake shows up as an empty table.
    removals = texts.count("移除")
    print(f"style rows rendered: {removals} (2 rules configured)")
    if removals < 2:
        problems.append(f"only {removals} style rows rendered for 2 rules")

    # The two buttons that can be pressed without a game.
    start = find_button(root, "開始")
    if start is not None:
        start.invoke()
        if getattr(controller, "started", None) is not None:
            if not controller.started:
                problems.append("開始 did not reach the controller")
            else:
                print(f"開始 passed {len(controller.started[0].highlights)} style rules to "
                      f"the controller, user_id={controller.started[0].user_id!r}")
        else:
            # The real controller: the message is what the window shows under the buttons.
            print(f"開始 (real controller): {controller.message}")
    for arrow, direction in (("→", "right"), ("←", "left"), ("↓", "down"), ("↑", "up")):
        button = find_button(root, arrow)
        if button is not None:
            button.invoke()
    nudges = getattr(controller, "nudges", None)
    if nudges is None:
        print("the position arrows were pressed; the real controller was nudged in place")
    elif [name for name, _step in nudges] != ["right", "left", "down", "up"]:
        problems.append(f"the arrows did not nudge in order: {nudges}")
    else:
        print(f"the four arrows nudged: {nudges}")

    if args.live:
        # A start/stop/start cycle, because that is the shape of the bug the player hit:
        # 停止 left the first overlay up, and the next 開始 stacked a second one on it.
        import time

        from dfbossreminder.services.window import find_game_window  # noqa: PLC0415

        def report(step: str) -> list:
            live = overlay_windows()
            where = live[0][1] if live else None
            print(f"{step}: {len(live)} overlay window(s)"
                  + (f", rect {where}" if where else ""))
            return live

        print(f"\ncontroller message: {controller.message}")
        if "運行中" not in controller.message:
            problems.append("the overlay did not start - start the game client and run this "
                            "again")
        else:
            time.sleep(args.seconds)
            print(f"after {args.seconds:.0f}s: the game window is "
                  f"{'still' if find_game_window() else 'no longer'} there and the readout "
                  f"kept drawing")
            up = report("after 開始")
            if len(up) != 1:
                problems.append(f"expected exactly one overlay window, found {len(up)}")
            first_rect = up[0][1] if up else None

            # Move it away with an arrow, then press 重新校正位置: it has to come back to
            # exactly where the 顯示位置 settings say. This is the button that replaced the
            # deleted auto-follow, so it is the one that has to be right.
            moved_away = False
            for _ in range(4):
                button = find_button(root, "→")
                if button is None:
                    break
                button.invoke()
                time.sleep(0.6)
            after_nudge = report("after four arrow presses")
            if first_rect and after_nudge and after_nudge[0][1] != first_rect:
                moved_away = True
            if not moved_away:
                problems.append("the arrow did not move the overlay, so realign cannot be "
                                "judged")

            realign_button = find_button(root, "重新校正位置")
            # The player's own reason for the button: they move the game window while
            # playing, the readout stays where the client used to be, and this brings it
            # back. So the game window is moved here by (120, 80) and put back afterwards -
            # a couple of seconds out of place, which is the price of testing the real
            # thing rather than the arithmetic alone.
            game = find_game_window()
            if game is None:
                problems.append("no game window to move, so re-anchoring cannot be judged")
            else:
                was = window_rect(game.hwnd)
                delta = (120, 80)
                move_window(game.hwnd, was[0] + delta[0], was[1] + delta[1])
                time.sleep(1.5)
                report("after moving the game window by " + str(delta))
                if realign_button is not None:
                    realign_button.invoke()
                    time.sleep(1.5)
                    moved = report("after 重新校正位置 with the window moved")
                    if moved and first_rect:
                        shifted = (moved[0][1][0] - first_rect[0], moved[0][1][1] - first_rect[1])
                        if shifted != delta:
                            problems.append(f"re-anchoring moved the readout by {shifted}, "
                                            f"not the window's {delta}")
                        else:
                            print(f"  -> the readout followed the game window exactly "
                                  f"({shifted})")
                move_window(game.hwnd, was[0], was[1])
                time.sleep(1.5)
                report("after putting the game window back")
                if realign_button is not None:
                    realign_button.invoke()
                    time.sleep(1.5)
                    back = report("after 重新校正位置 with the window back")
                    if back and first_rect and back[0][1] != first_rect:
                        problems.append(f"the readout did not return to {first_rect}: "
                                        f"{back[0][1]}")

            if realign_button is None:
                problems.append("no 重新校正位置 button in the window")

            print(f"stopping: {controller.stop()}")
            print(f"stopped, running={controller.running()}")
            left = report("after 停止")
            if left:
                problems.append(f"停止 left {len(left)} overlay window(s) on screen")
            # And 停止 then 開始 again must still be one window, not two.
            ok, message = controller.start(settings)
            print(f"second 開始: {message}")
            time.sleep(2.0)
            again = report("after a second 開始")
            if not ok or len(again) != 1:
                problems.append(f"a second start left {len(again)} overlay window(s)")
            print(f"final stop: {controller.stop()}")
            report("after the final 停止")

    # The window is kept until here: the live block presses its buttons, and a widget of a
    # destroyed root raises TclError instead of doing anything.
    root.destroy()
    if captured.getvalue():
        print("\n--- what the run printed ---")
        print(captured.getvalue().strip())

    if problems:
        print("\nPROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nPASS: the window has the styles table, the start button and the position "
          "arrows, and nothing of the whitelist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
