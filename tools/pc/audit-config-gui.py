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
            stream.reconfigure(encoding="utf-8", errors="replace")
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

    root.destroy()

    if args.live:
        # The overlay is up (or the refusal is in the controller's message). Give it time
        # to fetch and draw, look for its window, and take it down the way 停止 does.
        import time

        from dfbossreminder.services.window import find_game_window  # noqa: PLC0415

        print(f"\ncontroller message: {controller.message}")
        if "運行中" in controller.message:
            time.sleep(args.seconds)
            print(f"after {args.seconds:.0f}s: {controller.message}")
            print(f"the game window is {'still' if find_game_window() else 'no longer'} "
                  f"there, and the readout kept drawing")
            print(f"stopping: {controller.stop()}")
            print(f"stopped, running={controller.running()}")
        elif "not running" in controller.message:
            problems.append("the overlay did not start because the game is not running - "
                            "start the client and run this again")
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
