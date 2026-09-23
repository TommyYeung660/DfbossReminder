"""Validated settings, loaded from a JSON file and overridden per field.

Three rules hold everywhere in this module, and they exist because the previous
tool hard-coded its identifiers in ``config.py`` and had to be edited to change
anything:

* **Per-field fallback.** One bad value does not discard the rest of the file. A
  nonsense radius is clamped, a nonsense presentation falls back to the default,
  and only the offending field changes.
* **Clamped, not rejected.** A number is a number: ``radius_blocks = 9999`` becomes
  the documented maximum rather than an error, so the tool still runs.
* **Round-trips.** :func:`parse_settings` and :func:`to_dict` are inverses, which
  is what lets ``--set-user-id`` write a file this module reads back unchanged.

``user_id`` is the one value the player asked to be *remembered*: it is the
numeric Dead Frontier account id (``14008279``) whose ``gpscoords`` the profiler
publishes, and it is the only thing needed to know where the player is.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .bosses import DEFAULT_BIG_BOSSES
from .colours import hex_to_rgb as _hex_to_rgb
from .geometry import Block
from .styles import Highlight, StyleError, colour_for, parse_highlights
from .styles import to_dict as highlights_to_dict

MIN_USER_ID_LENGTH = 5
MAX_USER_ID_LENGTH = 12

PRESENTATIONS = ("overlay", "panel", "console")
# ``below-minimap`` is the in-game default: the readout hangs off the bottom of the
# region minimap, inside the client area, which is where the player is already
# looking and where it covers the least.
ANCHORS = ("below-minimap", "top-left", "top-right", "bottom-left", "bottom-right", "center")
DIRECTION_STYLES = ("zh", "en", "compact")
LANGUAGES = ("zh", "en")
ALIGNMENTS = ("left", "right", "center")

DEFAULT_BASE_URL = "https://www.dfprofiler.com"
DEFAULT_WAYPOINT = ("Secronom Bunker", Block(1054, 987))

# The region minimap's rectangle **in client coordinates**, at the 1280x720
# presentation this project is built for: measured off a live client capture
# (its "BUNKER" header at the top and its "1057 X 1017" readout at the bottom both
# sit inside it), and matching the sibling project's independently measured value.
DEFAULT_MINIMAP = (1060, 10, 215)

# Colours are ``#RRGGBB``. The list is bright green as asked; the default for a big
# boss is the same green and exists so it *can* be separated, since the format
# already distinguishes them.
DEFAULT_COLOURS = {
    "list": "#33FF33",
    "big": "#33FF33",
    "title": "#19C819",
    "note": "#9AA0A6",
    "background": "#0E0D0B",
    "border": "#2E4A2E",
}
COLOUR_KEYS = tuple(DEFAULT_COLOURS)
DEFAULT_OPACITY = 0.86    # kept for the settings window's slider default


@dataclass(frozen=True)
class Settings:
    """Everything the user can change, with the defaults this project ships."""

    user_id: str = ""
    base_url: str = DEFAULT_BASE_URL

    # The radius the second requirement names: how many blocks around the player
    # still counts as "nearby". Configurable at runtime and stored here.
    radius_blocks: int = 8

    # The third requirement used to be a whitelist filter; the player replaced it on
    # 2026-09-23 with **coordinate styles** - the cells stay, the filtering does not, and
    # instead a boss at a named cell is drawn in the colour that rule carries.
    highlights: tuple[Highlight, ...] = ()

    # A mission spawn is a special enemy at a fixed place for a mission reward,
    # not a boss cycle. Off by default because it is not what a boss run is.
    include_missions: bool = False

    # With no position there is no radius to measure, so the honest choice is to
    # say so and still list what is known rather than show an empty panel.
    show_all_without_player: bool = True

    poll_seconds: float = 20.0
    stale_seconds: float = 120.0

    presentation: str = "overlay"
    anchor: str = "below-minimap"
    offset_x: int = 14
    offset_y: int = 14
    width: int = 340
    # A **maximum**: the window grows and shrinks to fit what it has to show, so the
    # notes at the bottom are never clipped by a height chosen before the content was
    # known.
    height: int = 420
    max_rows: int = 12

    # The minimap's rectangle in client coordinates, and how far below it the
    # readout starts. These are what ``anchor = below-minimap`` is measured from.
    minimap_left: int = DEFAULT_MINIMAP[0]
    minimap_top: int = DEFAULT_MINIMAP[1]
    minimap_size: int = DEFAULT_MINIMAP[2]
    minimap_gap: int = 4

    font_size: int = 10
    # 300 = light. The client's HUD font ships exactly one face (its OS/2 table says 400,
    # its subfamily name says "Regular"), and weights 100 through 500 were measured to
    # draw byte-identical pixels on the game PC - so 300 is at the floor rather than
    # lighter than 400, and 700 and up make GDI synthesise a heavier face. There is no
    # lighter cut to reach for; the overlay reports what it asked for beside what it got.
    font_weight: int = 300
    colours: tuple[tuple[str, str], ...] = tuple(DEFAULT_COLOURS.items())
    # Zero means a fully transparent backing: only the glyphs are drawn, so the game
    # underneath is untouched. A text shadow keeps them readable over bright ground.
    opacity: float = 0.0
    text_shadow: bool = True
    # The language of everything that is not a boss line: the header, the notes, the
    # status. The boss lines themselves are a fixed format.
    language: str = "zh"

    # The bosses drawn with the "name | block | end time" form instead of a bearing.
    big_bosses: tuple[str, ...] = DEFAULT_BIG_BOSSES
    direction_style: str = "zh"
    # Empty means "let the overlay pick a fixed-pitch font that has CJK glyphs".
    # Set it to override, e.g. on a machine where the first choice is missing.
    font_face: str = ""
    # The client's own HUD font (VIPER NORA) is taken from the game's own assets when
    # it can be, so the readout matches the game's labels. Off makes the overlay use a
    # font already installed on the machine instead.
    game_font: bool = True
    align: str = "right"
    waypoints: tuple[tuple[str, Block], ...] = (DEFAULT_WAYPOINT,)

    def with_user_id(self, user_id: str) -> "Settings":
        return replace(self, user_id=user_id)

    @property
    def colour_map(self) -> dict[str, str]:
        return dict(self.colours)

    def colour(self, name: str) -> tuple[int, int, int]:
        """One theme colour as ``(r, g, b)``, falling back to the default.

        A missing or malformed key returns the shipped default rather than black, so
        a hand-edited settings file cannot make the readout invisible.
        """
        return _hex_to_rgb(self.colour_map.get(name, DEFAULT_COLOURS.get(name, "#FFFFFF")))

    def style_colour(self, block: Block) -> tuple[int, int, int] | None:
        """The colour a coordinate style gives this block, or None for the default.

        None rather than a colour is the answer that matters: "no rule matched" and
        "a rule matched the ordinary colour" are different, and only the caller knows
        whether a big boss's own colour should win.
        """
        found = colour_for(self.highlights, block)
        return _hex_to_rgb(found) if found else None


def normalize_user_id(value: object) -> str:
    """A DF account id is digits only; anything else is not one and is dropped.

    It is not zero-padded or trimmed to a length, because two accounts whose ids
    differ only in leading zeros would then collide. A value that is not all
    digits is refused rather than coerced - silently accepting ``"tommy660"``
    would fail later as "the profiler does not know this user".
    """
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text.isdigit():
        return ""
    if not MIN_USER_ID_LENGTH <= len(text) <= MAX_USER_ID_LENGTH:
        return ""
    return text


def _clamp_int(value: object, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            return default
    if isinstance(value, float):
        value = int(value)
    if not isinstance(value, int):
        return default
    return max(low, min(high, value))


def _clamp_float(value: object, default: float, low: float, high: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return default
    if not isinstance(value, (int, float)):
        return default
    return max(low, min(high, float(value)))


def _one_of(value: object, allowed: tuple[str, ...], default: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    return default


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    if isinstance(value, int):
        return bool(value)
    return default


def _colour(value: object, default: str) -> str:
    """A ``#RRGGBB`` string, normalised to upper case; anything else is dropped."""
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text.startswith("#"):
        text = "#" + text
    body = text[1:]
    if len(body) == 3 and all(char in "0123456789abcdefABCDEF" for char in body):
        body = "".join(char * 2 for char in body)
    if len(body) == 6 and all(char in "0123456789abcdefABCDEF" for char in body):
        return "#" + body.upper()
    return default


def _colours(value: object, default: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """The theme, merged over the defaults one key at a time.

    A file that names only the list colour keeps the shipped title, notes and
    backing, which is what "change one colour" should mean.
    """
    merged = dict(default)
    if isinstance(value, dict):
        for key in COLOUR_KEYS:
            if key in value:
                merged[key] = _colour(value.get(key), merged[key])
    return tuple((key, merged[key]) for key in COLOUR_KEYS)


def _big_bosses(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """The big-boss tier, as configured names.

    A list is honoured even when it is empty - that is a player saying "I have no big
    bosses configured", not a missing value; only a value that is not a list at all
    falls back to the default.
    """
    if not isinstance(value, (list, tuple)):
        return default
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
    return tuple(names)


def _text_field(value: object, default: str, limit: int = 64) -> str:
    if isinstance(value, str) and value.strip() and len(value.strip()) <= limit:
        return value.strip()
    return default


def _waypoints(value: object, default: tuple[tuple[str, Block], ...]) -> tuple[tuple[str, Block], ...]:
    if not isinstance(value, (list, tuple)):
        return default
    found: list[tuple[str, Block]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            x, y = int(item["x"]), int(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(item.get("label", "")).strip() or f"{x},{y}"
        found.append((label, Block(x, y)))
    return tuple(found)


def parse_settings(payload: object) -> Settings:
    """Read a settings mapping, falling back one field at a time."""
    if not isinstance(payload, dict):
        return Settings()
    defaults = Settings()
    try:
        highlights = parse_highlights(payload.get("highlights"))
    except StyleError:
        # A styles list with one bad rule loses the styles, not the account id.
        highlights = ()
    base_url = payload.get("base_url")
    return Settings(
        user_id=normalize_user_id(payload.get("user_id")),
        base_url=(base_url.strip().rstrip("/") if isinstance(base_url, str) and base_url.strip()
                  else defaults.base_url),
        radius_blocks=_clamp_int(payload.get("radius_blocks"), defaults.radius_blocks, 0, 200),
        highlights=highlights,
        include_missions=_as_bool(payload.get("include_missions"), defaults.include_missions),
        show_all_without_player=_as_bool(payload.get("show_all_without_player"),
                                         defaults.show_all_without_player),
        poll_seconds=_clamp_float(payload.get("poll_seconds"), defaults.poll_seconds, 5.0, 3600.0),
        stale_seconds=_clamp_float(payload.get("stale_seconds"), defaults.stale_seconds, 15.0, 3600.0),
        presentation=_one_of(payload.get("presentation"), PRESENTATIONS, defaults.presentation),
        anchor=_one_of(payload.get("anchor"), ANCHORS, defaults.anchor),
        offset_x=_clamp_int(payload.get("offset_x"), defaults.offset_x, -4000, 4000),
        offset_y=_clamp_int(payload.get("offset_y"), defaults.offset_y, -4000, 4000),
        width=_clamp_int(payload.get("width"), defaults.width, 220, 1600),
        height=_clamp_int(payload.get("height"), defaults.height, 90, 1200),
        max_rows=_clamp_int(payload.get("max_rows"), defaults.max_rows, 1, 40),
        direction_style=_one_of(payload.get("direction_style"), DIRECTION_STYLES, defaults.direction_style),
        font_face=_text_field(payload.get("font_face"), defaults.font_face),
        font_size=_clamp_int(payload.get("font_size"), defaults.font_size, 8, 32),
        font_weight=_clamp_int(payload.get("font_weight"), defaults.font_weight, 100, 900),
        colours=_colours(payload.get("colours"), defaults.colours),
        opacity=_clamp_float(payload.get("opacity"), defaults.opacity, 0.0, 1.0),
        text_shadow=_as_bool(payload.get("text_shadow"), defaults.text_shadow),
        language=_one_of(payload.get("language"), LANGUAGES, defaults.language),
        game_font=_as_bool(payload.get("game_font"), defaults.game_font),
        align=_one_of(payload.get("align"), ALIGNMENTS, defaults.align),
        minimap_left=_clamp_int(payload.get("minimap_left"), defaults.minimap_left, -2000, 4000),
        minimap_top=_clamp_int(payload.get("minimap_top"), defaults.minimap_top, -2000, 4000),
        minimap_size=_clamp_int(payload.get("minimap_size"), defaults.minimap_size, 40, 800),
        minimap_gap=_clamp_int(payload.get("minimap_gap"), defaults.minimap_gap, 0, 200),
        big_bosses=_big_bosses(payload.get("big_bosses"), defaults.big_bosses),
        waypoints=_waypoints(payload.get("waypoints"), defaults.waypoints),
    )


def to_dict(settings: Settings) -> dict:
    """The JSON form; :func:`parse_settings` reads it back field for field."""
    return {
        "user_id": settings.user_id,
        "base_url": settings.base_url,
        "radius_blocks": settings.radius_blocks,
        "highlights": highlights_to_dict(settings.highlights),
        "include_missions": settings.include_missions,
        "show_all_without_player": settings.show_all_without_player,
        "poll_seconds": settings.poll_seconds,
        "stale_seconds": settings.stale_seconds,
        "presentation": settings.presentation,
        "anchor": settings.anchor,
        "offset_x": settings.offset_x,
        "offset_y": settings.offset_y,
        "width": settings.width,
        "height": settings.height,
        "max_rows": settings.max_rows,
        "direction_style": settings.direction_style,
        "font_face": settings.font_face,
        "font_size": settings.font_size,
        "font_weight": settings.font_weight,
        "colours": settings.colour_map,
        "opacity": settings.opacity,
        "text_shadow": settings.text_shadow,
        "language": settings.language,
        "game_font": settings.game_font,
        "align": settings.align,
        "minimap_left": settings.minimap_left,
        "minimap_top": settings.minimap_top,
        "minimap_size": settings.minimap_size,
        "minimap_gap": settings.minimap_gap,
        "big_bosses": list(settings.big_bosses),
        "waypoints": [{"label": label, "x": block.x, "y": block.y}
                      for label, block in settings.waypoints],
    }
