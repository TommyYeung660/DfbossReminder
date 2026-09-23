"""The process: read settings, poll the profiler, plan, draw, fail closed.

The shape of one pass is fixed and small on purpose:

1. read the player's settings (once, from a JSON file, overridden by the command line);
2. fetch the boss map and the player's ``gpscoords``;
3. build the plan - everything within the radius;
4. draw it into the overlay (or the console).

Every step can fail without taking the tool down. A failed fetch keeps the last
known plan and marks it stale rather than blanking the screen, an absent game
window falls back to the screen, and a machine that is not Windows falls back to
the console. What the tool never does is guess: with no player position it says so
instead of assuming the origin, and a style rule or coordinate it cannot parse is
reported as the text that was wrong.

There is also the settings window, which is how the tool is normally started: it runs
the readout in this same process, so the player opens one program, presses 開始, and the
overlay appears. The console path is unchanged and is what the probes, ``--once`` and the
runbook use.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from . import __version__
from .domain.plan import Plan, build_plan
from .domain.settings import (
    ALIGNMENTS,
    ANCHORS,
    DEFAULT_BASE_URL,
    DIRECTION_STYLES,
    LANGUAGES,
    PRESENTATIONS,
    Settings,
    normalize_user_id,
    parse_settings,
    to_dict,
)
from .domain.styles import StyleError, parse_highlights
from .services.profiler import ProfilerClient, ProfilerError, fetch_state
from .services.gamefont import FONT_FAMILY as GAME_FONT_FAMILY
from .services.gamefont import ensure_cached as ensure_game_font
from .services.window import GameWindow, Rect, find_game_window, game_data_dir, screen_rect
from .ui import layout, view
from .ui.panel import Overlay, Row

DEFAULT_SETTINGS_PATH = "~/.dfbossreminder/settings.json"


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
    if args.highlight:
        try:
            updates["highlights"] = parse_highlights(args.highlight)
        except StyleError as error:
            raise SystemExit(f"--highlight: {error}") from error
        changed = True
    if args.highlight_add:
        try:
            added = parse_highlights(args.highlight_add)
        except StyleError as error:
            raise SystemExit(f"--highlight-add: {error}") from error
        updates["highlights"] = tuple(settings.highlights) + tuple(added)
        changed = True
    if args.no_highlights:
        updates["highlights"] = ()
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
    if args.font_weight is not None:
        updates["font_weight"] = args.font_weight
        changed = True
    if args.opacity is not None:
        updates["opacity"] = args.opacity
        changed = True
    if args.language:
        updates["language"] = args.language
        changed = True
    if args.align:
        updates["align"] = args.align
        changed = True
    if args.no_game_font:
        updates["game_font"] = False
        changed = True
    if args.text_shadow is not None:
        updates["text_shadow"] = args.text_shadow == "on"
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
        font_cache: Path | None = None,
        log=print,  # noqa: ANN001
    ) -> None:
        self.settings = settings
        self.use_client_area = use_client_area
        # Where the client's font is kept once it has been read out of its assets. It
        # belongs beside the settings, in this project's own state directory - never in
        # the repository, because the font is not this project's to redistribute.
        self.font_cache = font_cache
        self.log = log
        self.notes: list[str] = []
        self.overlay: Overlay | None = None
        self.window: GameWindow | None = None
        # A temporary adjustment on top of the configured offsets, moved by the settings
        # window's arrows. Deliberately **not** a setting and never saved: the position the
        # player configured is the one 顯示位置 says, so there is always something for
        # 重新校正位置 to return to. A nudge that overwrote the configuration would make
        # that button do nothing, which is exactly what it did before.
        self.adjustment: tuple[int, int] = (0, 0)
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

    def _corner(self, area: Rect, height: int) -> tuple[int, int]:
        """Where the window goes, honouring the ``below-minimap`` anchor.

        ``height`` is passed in because the window sizes itself to its content: an
        anchor on a bottom edge is measured *up* from that edge, so it has to know how
        tall the thing it is placing turned out to be.
        """
        left, top = self._anchored_corner(area, height)
        # The live adjustment, applied last so it means the same thing on every anchor.
        return left + self.adjustment[0], top + self.adjustment[1]

    def _anchored_corner(self, area: Rect, height: int) -> tuple[int, int]:
        """Where the configured position puts the window, before any live adjustment."""
        if self.settings.anchor == "below-minimap":
            # Measured from the client area, so it needs the client even when the
            # presentation is ``panel``; that is why the game window is required above.
            return layout.place_below_minimap(
                area.left, area.top, self.settings.minimap_left, self.settings.minimap_top,
                self.settings.minimap_size, self.settings.width, height,
                self.settings.minimap_gap, self.settings.offset_x, self.settings.offset_y)
        return layout.place(self.settings.anchor, area.left, area.top, area.width,
                            area.height, self.settings.width, height,
                            self.settings.offset_x, self.settings.offset_y)

    def _place(self, area_and_note: tuple[Rect, str]) -> None:
        area, note = area_and_note
        self.notes = [note]
        left, top = self._corner(area, self.settings.height)
        self.overlay = Overlay(left, top, self.settings.width, self.settings.height,
                               background=(*self.settings.colour("background"),
                                           int(255 * self.settings.opacity)),
                               border=self.settings.colour("border"),
                               title_colour=self.settings.colour("title"),
                               font_size=self.settings.font_size,
                               font_weight=self.settings.font_weight,
                               font_face=self.settings.font_face,
                               prefer_ascii=self.settings.direction_style == "en",
                               text_shadow=self.settings.text_shadow,
                               align=self.settings.align)
        if not self.settings.font_face:
            # Confirming a face needs a device context, so the font arrives through the
            # overlay rather than being passed into it.
            self.overlay.set_face(self._game_font_face())

    def _game_font_face(self) -> str:
        """The client's own HUD font, loaded privately from the client's own files.

        Not installed anywhere and not shipped: the bytes are read out of the game the
        tool is already reading, cached in this project's state directory, and loaded
        for this process only. When it cannot be had, the overlay falls back to a font
        the machine already has and says which one it used.
        """
        if not self.settings.game_font or self.overlay is None or self.font_cache is None:
            return ""
        if not hasattr(self.overlay, "gdi32"):        # a stub in a test
            return ""
        cache = self.font_cache
        data_dir = game_data_dir(self.window)
        if data_dir is None:
            self.notes.append("no game asset directory; using an installed font")
            return ""
        path = ensure_game_font(cache, data_dir)
        if path is None:
            self.notes.append(f"the game's font ({GAME_FONT_FAMILY}) was not found in its assets")
            return ""
        face = self.overlay.load_private_font(path, GAME_FONT_FAMILY)
        if not face:
            self.notes.append(f"could not load {path}")
            return ""
        self.notes.append(f"using the game's own font: {face}")
        return face

    def draw(self, plan: Plan, settings: Settings, account: str, status: str, stale: bool) -> None:
        self.settings = settings
        if self.overlay is None:
            return
        # Bosses only, and no title line: the window over the game is the list the player
        # reads while playing. The waypoints, the notes, the age and the header are all
        # still drawn by the console presentation (view.console_lines), which is where
        # "is this empty because there are no bosses or because the feed is down" is
        # answered.
        rows: tuple[Row, ...] = view.rows_for(plan, settings, status, stale, extras=False)
        rows = self._fit(rows, settings)
        self.overlay.set_content("", rows)

    def _fit(self, rows: tuple[Row, ...], settings: Settings) -> tuple[Row, ...]:
        """Size the window to its content, and say so if the maximum clips it.

        The window follows its content up to ``height``, and anything still over that
        limit is reported on its last line rather than silently vanishing. That last line
        is the one row of "extra" the overlay keeps: it only appears when bosses are
        actually being hidden, which is exactly the case where silence would be read as
        "that is the whole list".
        """
        area, _note = self._area()
        height = min(settings.height, self.overlay.height_for(len(rows)))
        left, top = self._corner(area, height)
        self.overlay.resize(left, top, settings.width, height)
        fitting = self.overlay.rows_fitting
        if len(rows) <= fitting:
            return rows
        # The warning row takes one of the slots it is counting, so the number is right.
        hidden = len(rows) - fitting + 1
        return rows[: fitting - 1] + (
            Row(view.status_text("hidden_rows", settings.language, count=hidden),
                settings.colour("note")),)

    def reposition(self, settings: Settings | None = None,
                   nudge: tuple[int, int] | None = None) -> str:
        """Put the window where the settings say it goes, plus any live adjustment.

        The readout used to *follow* the client, re-anchoring itself under the minimap
        every few seconds. The player asked for that to go on 2026-09-23: it moved the
        list under them while they were reading it, it re-measured a window that had not
        moved, and there was no way to switch it off. Position is now decided once at
        start and afterwards only when the player asks - with the position arrows (the
        live ``nudge``) or with 重新校正位置, which drops the nudge and re-reads these
        settings, and is how a game window that *has* moved gets accounted for.

        ``settings`` is optional so the caller can pass the values it is about to save:
        the presenter's own copy is a tick behind while the loop is running.
        """
        if self.overlay is None:
            return ""
        if settings is not None:
            self.settings = settings
        if nudge is not None:
            self.adjustment = (int(nudge[0]), int(nudge[1]))
        area, _note = self._area()
        left, top = self._corner(area, self.overlay.height)
        if (left, top) == (self.overlay.left, self.overlay.top):
            return ""
        self.overlay.move_to(left, top)
        return f"moved to ({left}, {top})"

    def describe(self) -> str:
        if self.overlay is None:
            return "overlay not created"
        return f"{self.overlay.describe()}; " + "; ".join(self.notes)

    def dump(self, path: str) -> str | None:
        return self.overlay.dump(path) if self.overlay is not None else None

    def close(self) -> None:
        if self.overlay is not None:
            self.overlay.close()


def make_presenter(settings: Settings, font_cache: Path | None = None, log=print):  # noqa: ANN001, ANN201
    """The presenter the settings ask for, degraded honestly when it is unavailable."""
    if settings.presentation == "console" or sys.platform != "win32":
        if settings.presentation != "console":
            log(f"{settings.presentation} needs Windows; falling back to the console")
        return ConsolePresenter()
    try:
        return OverlayPresenter(settings, use_client_area=settings.presentation == "overlay",
                                font_cache=font_cache, log=log)
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
        self.dumped = False
        # Requests from outside this loop, for the window's thread to answer. See
        # request_settings for why they cannot be done directly.
        self._requests: collections.deque = collections.deque()
        self._requests_lock = threading.Lock()
        # Which thread owns the overlay window: set by run(), and the one that is allowed
        # to move or destroy it.
        self.loop_thread: threading.Thread | None = None

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
        """``(status text, stale)`` - what the last line and the note colour say.

        The wording comes from the presentation, in the configured language, so the
        readout is Chinese without the plan knowing a language.
        """
        from .ui.view import status_text  # noqa: PLC0415 - presentation lives below

        language = self.settings.language
        if not self.last_success:
            if self.last_error:
                return status_text("no_data", language, reason=self.last_error), True
            return status_text("fetching", language), True
        age = now - self.last_success
        if age > self.settings.stale_seconds:
            return status_text("stale", language, age=age, reason=self.last_error or "ok"), True
        return status_text("fresh", language, age=age), False

    def tick(self, now: float) -> None:
        if now >= self.next_fetch:
            self.next_fetch = now + self.settings.poll_seconds
            self.refresh(now)
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

    def request_settings(self, settings: Settings, nudge: tuple[int, int] | None = None,
                         timeout: float = 5.0) -> str:
        """Ask this loop's own thread to adopt these settings and move the window.

        Nothing else may move the overlay. A window belongs to the thread that created it,
        and ``SetWindowPos`` from another thread sends messages to the owner and waits for
        it to process them - so with the settings window's thread calling it and this one
        never pumping a message loop, the call blocks **forever**. That is not a theory: the
        position arrows hung the settings window exactly this way.

        So the request is queued, the loop performs it between its sleep slices, and this
        waits for the result. The timeout is there because a fetch can be in flight; when it
        runs out, the answer says the move did not happen rather than pretending it did.
        """
        if not self._loop_is_this_thread():
            done = threading.Event()
            result: list[str] = [""]
            with self._requests_lock:
                self._requests.append((settings, nudge, done, result))
            if not done.wait(timeout=timeout):
                return ""
            return result[0]
        # Called from the loop's own thread (a test, or a future single-threaded caller):
        # do it here, there is nothing to hand over.
        self.settings = settings
        move = getattr(self.presenter, "reposition", None)
        return move(settings, nudge) if move else ""

    def _loop_is_this_thread(self) -> bool:
        """Whether this call may touch the window directly.

        True when the loop has not started (nothing owns a window yet, so there is nothing
        to hand over and no thread to wait for) or when this *is* the loop's thread.
        """
        return self.loop_thread is None or self.loop_thread is threading.current_thread()

    def _drain_requests(self) -> None:
        """Perform whatever the settings window has asked for, on this thread."""
        while True:
            with self._requests_lock:
                if not self._requests:
                    return
                settings, nudge, done, result = self._requests.popleft()
            self.settings = settings
            move = getattr(self.presenter, "reposition", None)
            try:
                result[0] = move(settings, nudge) if move else ""
            except Exception as error:                 # noqa: BLE001 - reported, not raised
                result[0] = f"移動失敗：{error}"
                self.log(f"could not move the readout: {error}")
            finally:
                done.set()

    def run(self, seconds: float | None = None, stop: threading.Event | None = None) -> None:
        """Loop until the time is up, the stop flag is set, or the process is interrupted.

        ``stop`` is what lets the settings window run this in a thread and take it back
        down on 停止. Both ends are checked before the first draw and after every sleep,
        so stopping never waits for a fetch. The same slices are where requests from the
        window (a nudge, a re-anchor) are carried out - on this thread, because this is the
        one that owns the window.
        """
        self.loop_thread = threading.current_thread()
        started = time.monotonic()
        self._drain_requests()
        self.tick(time.monotonic())
        try:
            while not (stop and stop.is_set()):
                if seconds is not None and time.monotonic() - started >= seconds:
                    break
                # The sleep is in slices so 停止 is responsive and so a request from the
                # window is answered within a tenth of a second: a full console interval is
                # five seconds, and a button that takes five seconds to react reads as a
                # button that did not work.
                slept = 0.0
                while slept < self.interval:
                    if stop and stop.is_set():
                        return
                    time.sleep(0.1)
                    slept += 0.1
                    self._drain_requests()
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
            "beyond_radius": plan.beyond_radius,
        },
        # Both forms: the code so a machine can act on it, the text so a person can
        # read what the run thought it was doing.
        "notes": [{"code": note.code, "values": note.values(),
                   "text": view.note_text(note, settings.language)} for note in plan.notes],
        "rows": [
            {"name": row.name, "amount": row.amount, "x": row.block.x, "y": row.block.y,
             "distance": row.distance, "bearing": row.direction(settings.direction_style),
             "minutes_left": round(row.minutes_left, 2), "mission": row.is_mission,
             # The colour the readout will actually draw, so a plan exported to a file
             # says which rows its style rules caught rather than leaving it to be
             # worked out again from the coordinates.
             "colour": "#%02X%02X%02X" % (settings.style_colour(row.block)
                                          or (settings.colour("big") if row.is_big
                                              else settings.colour("list")))}
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
    status = view.status_text("fresh", settings.language, age=0)
    for line in view.console_lines(plan, settings, status, False):
        log(line)
    if json_path:
        export_plan(plan, settings, account, Path(json_path),
                    {"boss_events": len(events), "player_known": player is not None})
        log(f"written to {json_path}")
    return 0


# ------------------------------------------------------------------- config window


class OverlayController:
    """Start, stop and place the readout on behalf of the settings window.

    The window and the readout are one program now: the player opens the settings window,
    presses 開始, and the overlay appears. Running the loop **in this process, in a
    thread** is what makes that a merge rather than two programs talking: 停止 really
    stops it, a position nudge takes effect immediately, and there is no second process
    to lose track of or to leave behind.

    The window is created, drawn and destroyed **on that one worker thread**, never on the
    one the settings window runs on. That is a Windows rule and not a style choice:
    ``DestroyWindow`` only works from the thread that created the window, so an overlay
    created on the GUI thread could not be taken down from the worker - 停止 appeared to
    do nothing, the window stayed on screen, and pressing 開始 again stacked a second
    overlay on top of it while two threads drew into the same device contexts. The player
    reported exactly that, ending in a crash. So the worker thread reports back through
    ``_ready`` when the overlay is up (or why it is not) and owns it from then on.

    Everything the window needs is a method here, so the window itself has no opinion
    about presenters, threads or Windows - which is also what keeps it testable.
    """

    # How long 開始 waits for the worker thread to say whether the overlay came up, and how
    # long 停止 waits for it to finish. Generous: both are local work with a window in it.
    START_TIMEOUT = 20.0
    STOP_TIMEOUT = 15.0
    # How long a position request waits for the loop's thread to carry it out. The loop
    # answers within a tenth of a second unless a fetch is in flight, so this is generous.
    REQUEST_TIMEOUT = 5.0

    def __init__(self, path: Path, log=print) -> None:  # noqa: ANN001
        self.path = path
        self.log = log
        self.watch: Watch | None = None
        # The live position adjustment, and the reason it lives here rather than in the
        # settings: see nudge.
        self.adjustment: tuple[int, int] = (0, 0)
        self.stop_event: threading.Event | None = None
        self.thread: threading.Thread | None = None
        self.message = "未啟動"
        self._ready = threading.Event()
        self._outcome: tuple[bool, str] = (False, "未啟動")

    # ------------------------------------------------------------------ lifecycle
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, settings: Settings) -> tuple[bool, str]:
        """Run the readout until :meth:`stop`. Returns ``(ok, message)``.

        A refusal is a return value rather than an exception: "the game is not running"
        is the most likely answer here, and the window shows it as a sentence instead of
        crashing the settings window the player is standing in.
        """
        if self.running():
            return True, "已經在運行"
        try:
            save_settings(self.path, settings)
        except OSError as error:
            self.log(f"could not save settings: {error}")
        self.stop_event = threading.Event()
        self._ready = threading.Event()
        self._outcome = (False, "逾時")
        # A daemon thread, so a window closed without 停止 still takes the overlay with
        # it: one program, one lifetime.
        self.thread = threading.Thread(target=self._run, args=(settings,),
                                       name="dfboss-overlay", daemon=True)
        self.thread.start()
        if not self._ready.wait(timeout=self.START_TIMEOUT):
            self.message = "overlay 起不來（等待逾時）"
            return False, self.message
        self.message = self._outcome[1]
        return self._outcome

    def _run(self, settings: Settings) -> None:
        """The readout's whole life, on one thread: create, draw, destroy."""
        stop = self.stop_event
        note = ""
        presenter = None
        try:
            presenter = make_presenter(settings, font_cache=self.path.parent / "game-font.ttf",
                                       log=self.log)
        except GameNotRunning as error:
            self._outcome = (False, str(error).splitlines()[0])
            self._ready.set()
            return
        except (OSError, RuntimeError) as error:
            self._outcome = (False, f"overlay 開不起來：{error}")
            self._ready.set()
            return
        if getattr(presenter, "kind", "") != "overlay":
            # make_presenter falls back to the console rather than failing. For a window
            # with a 開始 button that is the wrong answer to give quietly: the player would
            # press it and see nothing, so it is reported and the run ends here.
            note = f"只能開主控台模式（{presenter.describe()}）"
            self._outcome = (False, note)
            self._ready.set()
            presenter.close()
            return
        self.watch = Watch(settings, ProfilerClient(settings.base_url or DEFAULT_BASE_URL),
                           presenter, self.path, log=self.log)
        self._outcome = (True, f"運行中：{presenter.describe()}")
        self._ready.set()
        try:
            self.watch.run(stop=stop)
        except Exception as error:                     # noqa: BLE001 - reported, not raised
            # A thread that dies silently looks exactly like an overlay that works, so
            # the reason is kept where the window can show it.
            self.message = f"已停止（{error}）"
            self.log(f"the readout stopped: {error}")

    def stop(self) -> str:
        """Take the overlay down, and never claim to have done it when it has not.

        The handle is only dropped once the thread is really finished. Throwing it away on
        a timeout is what let a second 開始 build a second overlay over a first one that
        was still drawing - so a thread that will not finish stays reachable, and
        :meth:`running` keeps saying so.
        """
        if not self.running():
            self.message = "未啟動"
            return self.message
        if self.stop_event:
            self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=self.STOP_TIMEOUT)
        if self.thread and self.thread.is_alive():
            self.message = "停止中…（overlay 還在收尾，稍後再按）"
            return self.message
        self.thread = None
        self.watch = None
        self.message = "已停止"
        return self.message

    # -------------------------------------------------------------------- position
    def nudge(self, settings: Settings, direction: str, step: int) -> str:
        """Move the readout one step from where the configuration put it.

        The adjustment is **live and not saved**, and that is the point: 顯示位置 holds the
        position the player configured, so 重新校正位置 always has an original to return to.
        Saving the arrows into the offsets - which is what this did first - made that
        button a no-op, because "the configured position" moved every time an arrow was
        pressed.
        """
        dx, dy = layout.nudged(settings.anchor, self.adjustment[0],
                               self.adjustment[1], direction, step)
        moved = (dx, dy)
        if self.watch is not None:
            # Through the loop's thread: the window is not ours to move (see
            # Watch.request_settings). An empty answer means it did not get there in time.
            note = self.watch.request_settings(settings, moved, timeout=self.REQUEST_TIMEOUT)
            if not (note or self.watch.presenter.adjustment == moved):
                return f"位移 {dx}, {dy}（overlay 未即時移動，稍後再試）"
        self.adjustment = moved
        return f"位移 {dx}, {dy}"

    def realign(self, settings: Settings) -> tuple[bool, str]:
        """Put the readout back at the configured position: drop the nudge, re-read it.

        What replaced the old automatic following, in both senses the player needs: a game
        window that has moved leaves the overlay stranded with no way back, and an arrow
        adjustment needs a way to be undone. It adopts the form's settings as it goes, so a
        changed anchor or minimap rectangle takes effect without a restart.
        """
        if self.watch is None:
            return False, "未啟動：開始時就會用這個位置"
        note = self.watch.request_settings(settings, (0, 0), timeout=self.REQUEST_TIMEOUT)
        if not note and self.watch.presenter.adjustment != (0, 0):
            return False, "overlay 沒有回應（可能正在抓資料），稍後再按一次"
        self.adjustment = (0, 0)
        return True, note or "已在設定位置"


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
    parser.add_argument("--highlight", action="append", metavar="SPEC", default=[],
                        help='colour boss rows at these coordinates, e.g. "red=1015,999;1020,998" '
                             '(repeatable; replaces the list, "#RRGGBB" or a colour name)')
    parser.add_argument("--highlight-add", action="append", metavar="SPEC", default=[],
                        help="add one style rule to the existing list (repeatable)")
    parser.add_argument("--no-highlights", action="store_true", help="remove every style rule")
    parser.add_argument("--include-missions", action="store_true", help="also show mission spawns")
    parser.add_argument("--presentation", choices=PRESENTATIONS, help="overlay (in game) | panel (screen) | console")
    parser.add_argument("--anchor", choices=ANCHORS, help="which corner of the area to sit in")
    parser.add_argument("--offset", nargs=2, type=int, metavar=("X", "Y"),
                        help="nudge the readout from its anchor, in pixels")
    parser.add_argument("--poll", type=float, metavar="SECONDS", help="how often to refresh")
    parser.add_argument("--max-rows", type=int, metavar="N", help="how many bosses to list")
    parser.add_argument("--width", type=int, metavar="PX", help="readout width in pixels")
    parser.add_argument("--height", type=int, metavar="PX", help="readout height in pixels")
    parser.add_argument("--font-size", type=int, metavar="PX",
                        help="readout font size in pixels (default 10)")
    parser.add_argument("--font-weight", type=int, metavar="100-900",
                        help="readout font weight (default 300; the client's font has one "
                             "face and 100-500 all render the same, so 300 is the floor, "
                             "and the resolved weight is reported)")
    parser.add_argument("--opacity", type=float, metavar="0-1",
                        help="readout backing opacity; 0 is fully transparent")
    parser.add_argument("--text-shadow", choices=("on", "off"),
                        help="dark shadow behind the glyphs, for a transparent backing")
    parser.add_argument("--language", choices=LANGUAGES,
                        help="language of the header, notes and status (default zh)")
    parser.add_argument("--align", choices=ALIGNMENTS, help="readout text alignment")
    parser.add_argument("--no-game-font", action="store_true",
                        help="do not use the client's own HUD font")
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
                        help="open the settings window, which can start and stop the "
                             "overlay; it is also what happens with no arguments, and the "
                             "game does not need to be running")
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
    """Replace missing streams, and pin the encoding of the ones that exist.

    UTF-8, unconditionally, and chosen here rather than left to the environment. Two
    reasons, both found the hard way:

    * the **frozen exe does not honour ``PYTHONIOENCODING``** - the built executable
      wrote the console's own code page even with the variable set, so a redirected log
      came back as Big5 bytes that nothing but a Windows editor could read;
    * it is safe for a real console window too, and for a reason worth writing down:
      on Windows, Python writes to a console through ``WriteConsoleW`` (PEP 528), which
      takes UTF-16 and renders it with the console's font. The stream's encoding is
      only used to decode *our own bytes* on the way through, so UTF-8 is correct there
      as well - a Chinese character reaches the console as a Chinese character whatever
      the code page is set to.

    ``errors="replace"`` keeps a character a target cannot represent from killing a tool
    that has already done its work.
    """
    if sys.stdout is None:
        sys.stdout = _NullStream()          # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _NullStream()          # type: ignore[assignment]
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", line_buffering=True, errors="replace")
        except (ValueError, OSError):
            continue


def config_window(path: Path, settings: Settings, log=print) -> int:  # noqa: ANN001
    """Open the settings window, wired to start and stop the readout in this process.

    The controller is built here rather than inside ``ui/`` on purpose: the window must
    not need to know about presenters, threads or Windows to be drawable or testable,
    and this module is the one that already owns all three.
    """
    from .ui.config_gui import run_config  # noqa: PLC0415 - only needed on this path

    controller = OverlayController(path, log=log)
    return run_config(path, load=lambda: load_settings(path),
                      save=lambda value: save_settings(path, value),
                      controller=controller, log=log)


def main(argv: list[str] | None = None, default_to_config: bool = False) -> int:
    """Run the tool. ``default_to_config`` is what makes it one program.

    The entry scripts pass it, so a bare double-click opens the settings window instead of
    printing a usage error - and the window is where the overlay is started from. The
    flag is explicit rather than "no arguments means GUI", because a test that calls
    ``main([])`` must not open a window on whatever machine runs the suite.
    """
    _make_streams_safe()
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(arguments)
    path = settings_path(args.settings)
    if default_to_config and not arguments:
        return config_window(path, load_settings(path))
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
        return config_window(path, settings)

    if not settings.user_id and not args.once:
        print("no Dead Frontier account id is set. Add one and it will be remembered:\n"
              "  dfboss --user-id 14008279\n", file=sys.stderr)
        return 2

    client = ProfilerClient(settings.base_url or DEFAULT_BASE_URL)
    if args.once:
        return run_once(settings, client, args.json)

    try:
        presenter = make_presenter(settings, font_cache=path.parent / "game-font.ttf", log=print)
    except GameNotRunning as error:
        print(str(error), file=sys.stderr)
        return 3
    print(f"DFBossReminder {__version__} - {presenter.describe()}")
    watch = Watch(settings, client, presenter, path, dump_frame=args.dump_frame, log=print)
    try:
        watch.run(args.seconds or None)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
