"""The process: read settings, poll the profiler, plan, draw, fail closed.

The shape of one pass is fixed and small on purpose:

1. read the player's settings (once, from a JSON file, overridden by the command line);
2. fetch the boss map and the player's ``gpscoords``;
3. build the plan - whitelist first, then the radius;
4. draw it into the overlay (or the console).

Every step can fail without taking the tool down. A failed fetch keeps the last
known plan and marks it stale rather than blanking the screen, an absent game
window falls back to the screen, and a machine that is not Windows falls back to
the console. What the tool never does is guess: with no player position it says so
instead of assuming the origin, and with a whitelist entry it cannot parse it says
which entry was wrong.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from . import __version__
from .domain.plan import Plan, build_plan
from .domain.settings import (
    ANCHORS,
    DEFAULT_BASE_URL,
    DIRECTION_STYLES,
    PRESENTATIONS,
    Settings,
    normalize_user_id,
    parse_settings,
    to_dict,
)
from .domain.whitelist import WhitelistError, parse_whitelist
from .services.profiler import ProfilerClient, ProfilerError, fetch_state
from .services.window import GameWindow, Rect, find_game_window, screen_rect
from .ui import layout, view
from .ui.panel import Overlay, Row

DEFAULT_SETTINGS_PATH = "~/.dfbossreminder/settings.json"
TOGGLE_HOTKEY_ID = 1
DEFAULT_TOGGLE_HOTKEY = "F8"


# --------------------------------------------------------------------------- settings


def settings_path(explicit: str = "") -> Path:
    """Where settings live, with ``~`` expanded and the parent created on save."""
    return Path(explicit).expanduser() if explicit else Path(DEFAULT_SETTINGS_PATH).expanduser()


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"could not read {path}: {error}; using defaults", file=sys.stderr)
        return Settings()
    return parse_settings(payload)


def save_settings(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_dict(settings), indent=2, ensure_ascii=False), encoding="utf-8")


def apply_overrides(settings: Settings, args: argparse.Namespace) -> tuple[Settings, bool]:
    """Fold the command line into the settings; returns ``(settings, should_save)``.

    Anything given on the command line is also remembered, because the whole point
    of the first requirement is that the player sets these once. ``--no-save`` turns
    that off for a one-off look.
    """
    changed = False
    updates: dict = {}

    if args.set_user_id is not None:
        user_id = normalize_user_id(args.set_user_id)
        if not user_id:
            raise SystemExit(f"{args.set_user_id!r} is not a Dead Frontier account id "
                             f"(digits only, e.g. 14008279)")
        updates["user_id"] = user_id
        changed = True
    if args.radius is not None:
        updates["radius_blocks"] = args.radius
        changed = True
    if args.direction_style:
        updates["direction_style"] = args.direction_style
        changed = True
    if args.whitelist is not None:
        try:
            updates["whitelist"] = parse_whitelist(args.whitelist)
        except WhitelistError as error:
            raise SystemExit(f"--whitelist: {error}") from error
        changed = True
    if args.whitelist_add:
        try:
            combined = list(settings.whitelist) + list(parse_whitelist(";".join(args.whitelist_add)))
        except WhitelistError as error:
            raise SystemExit(f"--whitelist-add: {error}") from error
        updates["whitelist"] = tuple(combined)
        changed = True
    if args.whitelist_mode is not None:
        updates["whitelist_mode"] = args.whitelist_mode == "on"
        changed = True
    if args.presentation:
        updates["presentation"] = args.presentation
        changed = True
    if args.anchor:
        updates["anchor"] = args.anchor
        changed = True
    if args.offset:
        updates["offset_x"], updates["offset_y"] = args.offset
        changed = True
    if args.poll is not None:
        updates["poll_seconds"] = args.poll
        changed = True
    if args.max_rows is not None:
        updates["max_rows"] = args.max_rows
        changed = True
    if args.width is not None:
        updates["width"] = args.width
        changed = True
    if args.height is not None:
        updates["height"] = args.height
        changed = True
    if args.font:
        updates["font_face"] = args.font
        changed = True
    if args.font_size is not None:
        updates["font_size"] = args.font_size
        changed = True
    if args.include_missions:
        updates["include_missions"] = True
        changed = True
    if args.big_boss:
        names = list(settings.big_bosses)
        for name in args.big_boss:
            if name.strip() and name.strip() not in names:
                names.append(name.strip())
        updates["big_bosses"] = tuple(names)
        changed = True

    if updates:
        settings = replace(settings, **updates)
        # Re-validate through the normalizer so a clamped field is clamped the same
        # way it would be coming out of the file, and not only out of the file.
        settings = parse_settings(to_dict(settings))
    return settings, changed and not args.no_save


# --------------------------------------------------------------------------- presenters


class ConsolePresenter:
    """Print the readout. Works on every OS and is what a dev machine sees."""

    kind = "console"

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self.last = ""

    def draw(self, plan: Plan, settings: Settings, account: str, status: str, stale: bool) -> None:
        if self.quiet:
            return
        # The status line carries an age that changes every tick, so the de-duplication
        # key is the plan itself: a terminal prints a new block when something changed,
        # not once per poll.
        block = "\n".join(view.console_lines(plan, settings, "", stale))
        if block == self.last:
            return
        self.last = block
        stamp = time.strftime("%H:%M:%S")
        print(f"\n--- {stamp} {status} " + "-" * 30)
        print(block)

    def describe(self) -> str:
        return "console output"

    def follow(self, window: GameWindow | None) -> str:
        return ""

    def hotkey(self) -> str | None:
        return None

    def close(self) -> None:
        return None


class GameNotRunning(RuntimeError):
    """Raised when an overlay was asked for but the game is not running."""


def game_window_or_refuse(log=print):  # noqa: ANN001, ANN201
    """The game window, or a refusal.

    The overlay is a readout *of the running client*: placed relative to its client
    area, showing where its player is. Without the client there is no rectangle to
    anchor to and no player to measure from, so the window is not opened at all
    rather than being placed somewhere arbitrary. The console presentation is
    unaffected, because that is how the tool is checked before a game is started.
    """
    window = find_game_window()
    if window is None:
        raise GameNotRunning(
            "the Dead Frontier client is not running, so the overlay was not opened.\n"
            "Start the game first, or use --presentation console / --once for a "
            "text-only look."
        )
    return window


class OverlayPresenter:
    """The layered click-through window, anchored to the client area or the screen."""

    kind = "overlay"

    def __init__(
        self,
        settings: Settings,
        use_client_area: bool,
        hotkey: str = DEFAULT_TOGGLE_HOTKEY,
        log=print,  # noqa: ANN001
    ) -> None:
        self.settings = settings
        self.use_client_area = use_client_area
        self.hotkey_name = hotkey
        self.log = log
        self.notes: list[str] = []
        self.overlay: Overlay | None = None
        self.window: GameWindow | None = None
        self.hotkey_registered = False
        # Every overlay presentation needs the client: ``overlay`` and ``below-minimap``
        # to anchor inside it, and ``panel`` because a readout of a game that is not
        # running has nothing to say. This raises GameNotRunning, which main reports.
        self.window = game_window_or_refuse(log)
        self._place(self._area())

    def _area(self) -> tuple[Rect, str]:
        """The rectangle to anchor to, and a note about which one it was."""
        if self.use_client_area:
            mark = ""
            if self.window is not None and self.window.exclusive_fullscreen:
                mark = " (client covers the screen: fullscreen or borderless)"
            return self.window.client, f"anchored to the game client{mark}"
        return screen_rect() or Rect(0, 0, self.settings.width, self.settings.height), \
            "anchored to the screen"

    def _corner(self, area: Rect) -> tuple[int, int]:
        """Where the window goes, honouring the ``below-minimap`` anchor."""
        if self.settings.anchor == "below-minimap":
            # Measured from the client area, so it needs the client even when the
            # presentation is ``panel``; that is why the game window is required above.
            return layout.place_below_minimap(
                area.left, area.top, self.settings.minimap_left, self.settings.minimap_top,
                self.settings.minimap_size, self.settings.width, self.settings.height,
                self.settings.minimap_gap)
        return layout.place(self.settings.anchor, area.left, area.top, area.width,
                            area.height, self.settings.width, self.settings.height,
                            self.settings.offset_x, self.settings.offset_y)

    def _place(self, area_and_note: tuple[Rect, str]) -> None:
        area, note = area_and_note
        self.notes = [note]
        left, top = self._corner(area)
        self.overlay = Overlay(left, top, self.settings.width, self.settings.height,
                               background=(*self.settings.colour("background"),
                                           int(255 * self.settings.opacity)),
                               border=self.settings.colour("border"),
                               title_colour=self.settings.colour("title"),
                               font_size=self.settings.font_size,
                               font_face=self.settings.font_face,
                               prefer_ascii=self.settings.direction_style == "en")
        if self.hotkey_name:
            # Reported either way, because "the toggle works" is a claim that needs a
            # record: a silent failure here looks exactly like a hotkey nobody pressed.
            self.hotkey_registered = self.overlay.register_hotkey(self.hotkey_name, TOGGLE_HOTKEY_ID)
            self.notes.append(f"{self.hotkey_name} toggles whitelist mode"
                              if self.hotkey_registered
                              else f"could NOT register {self.hotkey_name} as a hotkey")

    def draw(self, plan: Plan, settings: Settings, account: str, status: str, stale: bool) -> None:
        self.settings = settings
        if self.overlay is None:
            return
        rows: tuple[Row, ...] = view.rows_for(plan, settings, status, stale)
        self.overlay.set_content(view.title_line(plan, settings, account), rows)

    def follow(self, window: GameWindow | None) -> str:
        """Re-anchor when the client moves; returns a note when the anchor changed."""
        if self.overlay is None or window is None:
            return ""
        if not self.use_client_area and self.settings.anchor != "below-minimap":
            return ""
        area = window.client
        left, top = self._corner(area)
        if (left, top) != (self.overlay.left, self.overlay.top):
            self.overlay.move_to(left, top)
            return f"moved with the client to ({left}, {top})"
        return ""

    def hotkey(self) -> str | None:
        if self.overlay is not None and self.hotkey_registered and \
                self.overlay.hotkey_pressed(TOGGLE_HOTKEY_ID):
            return "toggle-whitelist"
        return None

    def describe(self) -> str:
        if self.overlay is None:
            return "overlay not created"
        return f"{self.overlay.describe()}; " + "; ".join(self.notes)

    def dump(self, path: str) -> str | None:
        return self.overlay.dump(path) if self.overlay is not None else None

    def close(self) -> None:
        if self.overlay is not None:
            if self.hotkey_registered:
                self.overlay.unregister_hotkey(TOGGLE_HOTKEY_ID)
            self.overlay.close()


def make_presenter(settings: Settings, log=print):  # noqa: ANN001, ANN201
    """The presenter the settings ask for, degraded honestly when it is unavailable."""
    if settings.presentation == "console" or sys.platform != "win32":
        if settings.presentation != "console":
            log(f"{settings.presentation} needs Windows; falling back to the console")
        return ConsolePresenter()
    try:
        return OverlayPresenter(settings, use_client_area=settings.presentation == "overlay", log=log)
    except GameNotRunning:
        # Requirement: no game, no overlay. Falling back to the console here would
        # silently ignore the setting the player chose, so it is reported instead.
        raise
    except (OSError, RuntimeError) as error:
        log(f"could not create the overlay ({error}); falling back to the console")
        return ConsolePresenter()


# --------------------------------------------------------------------------- the loop


class Watch:
    """One fetch per poll interval, one draw per tick, and never a guess."""

    def __init__(
        self,
        settings: Settings,
        client: ProfilerClient,
        presenter,
        path: Path,
        dump_frame: str = "",
        log=print,  # noqa: ANN001
    ) -> None:
        self.settings = settings
        self.client = client
        self.presenter = presenter
        self.path = path
        self.dump_frame = dump_frame
        self.log = log
        self.events: list = []
        self.player = None
        self.account = ""
        self.last_success = 0.0
        self.last_error = ""
        self.failures = 0
        self.next_fetch = 0.0
        self.next_window_check = 0.0
        self.dumped = False

    # ------------------------------------------------------------------ fetching
    def refresh(self, now: float) -> None:
        """Fetch once. A failure is recorded, not raised, and the old plan stands."""
        try:
            events, player, account = fetch_state(self.client, self.settings)
        except ProfilerError as error:
            self.failures += 1
            self.last_error = str(error)
            self.log(f"fetch failed ({self.failures}): {error}")
            return
        self.events = events
        self.player = player
        self.account = account
        self.last_success = now
        self.last_error = ""
        self.failures = 0
        self.log(f"fetched {len(events)} boss events; player "
                 f"{player if player else 'position unknown'}")

    # -------------------------------------------------------------------- drawing
    def plan(self, now: float) -> Plan:
        return build_plan(self.events, self.player, self.settings, time.time())

    def status(self, now: float) -> tuple[str, bool]:
        """``(status text, stale)`` - what the header and the note colour say."""
        if not self.last_success:
            return (f"no data yet: {self.last_error}" if self.last_error else "fetching ..."), True
        age = now - self.last_success
        stale = age > self.settings.stale_seconds
        if stale:
            return f"stale {age:.0f}s (last: {self.last_error or 'ok'})", True
        return f"updated {age:.0f}s ago", False

    def tick(self, now: float) -> None:
        if now >= self.next_fetch:
            self.next_fetch = now + self.settings.poll_seconds
            self.refresh(now)
        if now >= self.next_window_check:
            self.next_window_check = now + self.settings.watch_pid_seconds
            note = self.presenter.follow(find_game_window() if self.settings.presentation == "overlay"
                                         else None)
            if note:
                self.log(note)
        action = self.presenter.hotkey()
        if action == "toggle-whitelist":
            self.toggle_whitelist()
        status, stale = self.status(now)
        self.presenter.draw(self.plan(now), self.settings, self.account, status, stale)
        if self.dump_frame and not self.dumped:
            # The overlay's own surface, not a screenshot: a layered window is not
            # reproduced by a screen capture on every display configuration.
            dump = getattr(self.presenter, "dump", None)
            written = dump(self.dump_frame) if dump else None
            if written:
                self.dumped = True
                self.log(f"overlay surface written to {written}; {self.presenter.describe()}")

    def toggle_whitelist(self) -> None:
        """Flip the whitelist mode, remember it, and say so in the log."""
        mode = not self.settings.whitelist_mode
        self.settings = replace(self.settings, whitelist_mode=mode)
        if mode and not self.settings.whitelist:
            self.log("whitelist mode ON, but the whitelist is empty - nothing will be shown")
        else:
            self.log(f"whitelist mode {'ON' if mode else 'OFF'} "
                     f"({len(self.settings.whitelist)} entries)")
        try:
            save_settings(self.path, self.settings)
        except OSError as error:
            self.log(f"could not save settings: {error}")

    def run(self, seconds: float) -> None:
        started = time.monotonic()
        now = time.monotonic()
        self.tick(now)
        try:
            while time.monotonic() - started < seconds:
                time.sleep(self.interval)
                self.tick(time.monotonic())
        finally:
            self.presenter.close()

    @property
    def interval(self) -> float:
        """How often to tick. A window wants responsiveness; a terminal wants quiet.

        Half a second makes the toggle hotkey feel instant and is cheap enough to
        poll a window rectangle; the fetch and the window check are gated separately,
        so this is only the cost of a plan rebuild.
        """
        return 5.0 if getattr(self.presenter, "kind", "") == "console" else 0.5


# --------------------------------------------------------------------------- one-shot


def export_plan(plan: Plan, settings: Settings, account: str, path: Path, fetched: dict) -> None:
    payload = {
        "version": __version__,
        "settings": to_dict(settings),
        "account": account,
        "player": {"x": plan.player.x, "y": plan.player.y} if plan.player else None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fetched": fetched,
        "counts": {
            "total_sightings": plan.total_sightings,
            "nearby_sightings": plan.nearby_sightings,
            "shown": plan.shown,
            "suppressed_by_whitelist": plan.suppressed_by_whitelist,
            "beyond_radius": plan.beyond_radius,
        },
        "notes": list(plan.notes),
        "rows": [
            {"name": row.name, "amount": row.amount, "x": row.block.x, "y": row.block.y,
             "distance": row.distance, "bearing": row.direction(settings.direction_style),
             "minutes_left": round(row.minutes_left, 2), "mission": row.is_mission}
            for row in plan.rows
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_once(settings: Settings, client: ProfilerClient, json_path: str = "", log=print) -> int:  # noqa: ANN001
    """Fetch once, print the plan, optionally write it, and exit."""
    try:
        events, player, account = fetch_state(client, settings)
    except ProfilerError as error:
        log(f"fetch failed: {error}")
        return 1
    plan = build_plan(events, player, settings, time.time())
    for line in view.console_lines(plan, settings, "updated 0s ago", False):
        log(line)
    if json_path:
        export_plan(plan, settings, account, Path(json_path),
                    {"boss_events": len(events), "player_known": player is not None})
        log(f"written to {json_path}")
    return 0


# --------------------------------------------------------------------------- cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dfboss",
        description="Show the Dead Frontier bosses near the player, over the game.",
    )
    parser.add_argument("--version", action="version", version=f"dfbossreminder {__version__}")
    parser.add_argument("--settings", default="", help=f"settings file (default {DEFAULT_SETTINGS_PATH})")
    parser.add_argument("--user-id", dest="set_user_id", metavar="ID",
                        help="Dead Frontier account id to remember, e.g. 14008279")
    parser.add_argument("--radius", type=int, metavar="BLOCKS",
                        help="how many blocks around the player count as nearby")
    parser.add_argument("--whitelist", metavar="SPEC",
                        help='replace the whitelist, e.g. "1055,986;1057,1017:2"')
    parser.add_argument("--whitelist-add", action="append", metavar="SPEC", default=[],
                        help="add coordinates to the whitelist (repeatable)")
    parser.add_argument("--whitelist-mode", choices=("on", "off"), help="turn whitelist mode on or off")
    parser.add_argument("--include-missions", action="store_true", help="also show mission spawns")
    parser.add_argument("--presentation", choices=PRESENTATIONS, help="overlay (in game) | panel (screen) | console")
    parser.add_argument("--anchor", choices=ANCHORS, help="which corner of the area to sit in")
    parser.add_argument("--offset", nargs=2, type=int, metavar=("X", "Y"), help="inset from the corner")
    parser.add_argument("--poll", type=float, metavar="SECONDS", help="how often to refresh")
    parser.add_argument("--max-rows", type=int, metavar="N", help="how many bosses to list")
    parser.add_argument("--width", type=int, metavar="PX", help="readout width in pixels")
    parser.add_argument("--height", type=int, metavar="PX", help="readout height in pixels")
    parser.add_argument("--font-size", type=int, metavar="PX",
                        help="readout font size in pixels (default 12)")
    parser.add_argument("--font", metavar="FACE",
                        help="overlay font; default picks a fixed-pitch face with CJK glyphs")
    parser.add_argument("--big-boss", action="append", metavar="NAME", default=[],
                        help="treat this boss as big/ultra: shown with its end time "
                             "(repeatable; the settings window edits the whole list)")
    parser.add_argument("--direction-style", choices=DIRECTION_STYLES,
                        help="zh (3右2上) or en (E3N2) for the bearing words")
    parser.add_argument("--once", action="store_true", help="fetch once, print, and exit")
    parser.add_argument("--json", default="", metavar="PATH", help="write the plan as JSON")
    parser.add_argument("--dump-frame", default="", metavar="PATH",
                        help="write the overlay's own surface to a BMP once, then keep running")
    parser.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = run until stopped)")
    parser.add_argument("--show-config", action="store_true", help="print the effective settings and exit")
    parser.add_argument("--config", action="store_true",
                        help="open the settings window (whitelist, font size, colours); "
                             "the game does not need to be running")
    parser.add_argument("--no-save", action="store_true", help="do not write overrides back to the file")
    return parser


class _NullStream:
    """Stands in for stdout/stderr in a windowed build, where both are ``None``.

    A ``--noconsole`` exe has no standard streams, and ``print`` to ``None`` raises.
    Rather than guard every message, the streams are replaced once, at the top of
    :func:`main`, so a windowed build degrades to silence instead of a crash.
    """

    def write(self, *_args) -> int:  # noqa: ANN002
        return 0

    def flush(self) -> None:
        return None

    def reconfigure(self, **_kwargs) -> None:  # noqa: ANN003
        return None


def _make_streams_safe() -> None:
    if sys.stdout is None:
        sys.stdout = _NullStream()          # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NullStream()          # type: ignore[assignment]
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(line_buffering=True, errors="replace")
        except (ValueError, OSError):
            continue


def main(argv: list[str] | None = None) -> int:
    _make_streams_safe()
    args = build_parser().parse_args(argv)
    path = settings_path(args.settings)
    try:
        settings, should_save = apply_overrides(load_settings(path), args)
    except SystemExit as error:
        print(error, file=sys.stderr)
        return 2

    if should_save:
        try:
            save_settings(path, settings)
            print(f"settings saved to {path}")
        except OSError as error:
            print(f"could not save settings: {error}", file=sys.stderr)

    if args.show_config:
        print(json.dumps(to_dict(settings), indent=2, ensure_ascii=False))
        return 0

    if args.config:
        # Deliberately before the user-id check and before any presenter: the window
        # is how the id gets set, and it must work with the game closed.
        from .ui.config_gui import run_config  # noqa: PLC0415 - only needed for this flag

        return run_config(path, load=lambda: load_settings(path),
                          save=lambda value: save_settings(path, value), log=print)

    if not settings.user_id and not args.once:
        print("no Dead Frontier account id is set. Add one and it will be remembered:\n"
              "  dfboss --user-id 14008279\n", file=sys.stderr)
        return 2

    client = ProfilerClient(settings.base_url or DEFAULT_BASE_URL)
    if args.once:
        return run_once(settings, client, args.json)

    try:
        presenter = make_presenter(settings, log=print)
    except GameNotRunning as error:
        print(str(error), file=sys.stderr)
        return 3
    print(f"DFBossReminder {__version__} - {presenter.describe()}")
    watch = Watch(settings, client, presenter, path, dump_frame=args.dump_frame, log=print)
    if args.seconds:
        watch.run(args.seconds)
        return 0
    try:
        watch.run(float("inf"))
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
