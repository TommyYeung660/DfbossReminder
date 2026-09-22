"""Turning a plan into the lines the player reads.

The overlay and the console print the same thing, so the text and its colour are
built once, here, as data. That is also what makes the readout testable: the rows
are tuples, not pixels, so a test can assert the exact line the player will see.

The line format is a compact, self-delimiting strip meant to hang under the region
minimap, and the boss tier picks between its two forms:

```text
6 x Bandits | 1052 x 1018 | 5LD1      # a normal boss: where it is from the player
Devil Hound | 1052 x 1018 | 18:00     # a big/ultra boss: when it despawns instead
```

A normal boss is one you walk to, so the bearing is the useful third field. A big
boss is a special spawn with a long window, so its expiry time is. The block
coordinate is always absolute (the boss map's own grid), which is what makes a row
checkable against the game's minimap readout.
"""

from __future__ import annotations

import unicodedata

from ..domain.geometry import Bearing
from ..domain.plan import Plan
from ..domain.settings import Settings
from .panel import Row

# How much of a boss name is kept before it is elided. The panel elides too, but
# capping here keeps a pathological name from dominating the strip.
NAME_LIMIT = 34

# The readout is a narrow strip, so the name budget is derived from the configured
# width and font size instead of being a constant: a fixed budget let a long name
# ("1 x Evolved Longarms + 1 x Irradiated ...") run past the panel, where the
# window's own ellipsis then ate the block coordinate and the bearing - exactly the
# two fields the player needs. The name is the field that gives way.
NAME_FLOOR = 12
CHAR_WIDTH_RATIO = 0.62          # a monospace glyph, as a fraction of the font size
SIDE_PADDING = 18


def columns_for(settings: Settings) -> int:
    """How many monospace columns fit across the readout."""
    per_char = max(4.0, settings.font_size * CHAR_WIDTH_RATIO)
    return max(20, int((settings.width - SIDE_PADDING) / per_char))


def name_budget(settings: Settings, tail: str) -> int:
    """Columns left for the name, given everything that follows it on the line.

    ``tail`` is the whole remainder - the block, the separator and the third field -
    because leaving any of it out of the subtraction is what let a long name overflow
    in the first place.
    """
    spare = columns_for(settings) - display_width(tail) - len(" | ")
    return max(NAME_FLOOR, min(NAME_LIMIT, spare))


def display_width(text: str) -> int:
    """How many columns the text occupies, counting a wide character as two.

    Kept from the first version of this readout, where padding by ``len()`` pushed
    the last field past the panel; nothing pads by width any more, but a name that
    is mostly wide characters must still be measured correctly to be elided.
    """
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in text)


def _fit(text: str, columns: int) -> str:
    """Truncate to a display width, with an ellipsis that itself fits."""
    if display_width(text) <= columns:
        return text
    kept = ""
    for char in text:
        if display_width(kept + char) > columns - 1:
            break
        kept += char
    return kept + "…"


def block_text(block) -> str:  # noqa: ANN001
    """A block the way the game prints it: ``1057 X 1017`` in its own readout."""
    return f"{block.x} x {block.y}"


def title_line(plan: Plan, settings: Settings, account: str = "") -> str:
    """``DFBossReminder  tommy660  1057,1017  3 nearby``, trimmed to the width.

    The strip under the minimap is narrow, so the longest form that fits is used and
    the account name is the first thing dropped: the block and the count are what say
    the readout is alive and where it thinks the player is.
    """
    where = str(plan.player) if plan.player else "at ?"
    nearby = f"{plan.nearby_sightings} nearby" + ("  [whitelist]" if settings.whitelist_mode else "")
    for candidate in (f"DFBossReminder  {account}  {where}  {nearby}" if account else "",
                      f"DFBossReminder  {where}  {nearby}",
                      f"DFBossReminder  {where}",
                      "DFBossReminder"):
        if candidate and display_width(candidate) <= columns_for(settings):
            return candidate
    return "DFBossReminder"


def boss_line(settings: Settings, row) -> str:  # noqa: ANN001
    """One boss in the requested format, chosen by its tier.

    Every field is separated by ``|`` and the count stays in the name because the
    boss map already publishes it as ``"6 x Bandits"``; a big boss drops it, so
    ``"Devil Hound"`` reads as the boss rather than as a group size of one.
    """
    field = row.end_clock() if row.is_big else row.direction("compact")
    name = row.short_name if row.is_big else row.name
    tail = f"{block_text(row.block)} | {field}"
    return f"{_fit(name, name_budget(settings, tail))} | {tail}"


def waypoint_line(label: str, block, bearing, settings: Settings) -> str:
    """A known place in the same shape, so the strip reads as one table."""
    tail = f"{block_text(block)} | {bearing.compact()}"
    return f"{_fit(label, name_budget(settings, tail))} | {tail}"


def rows_for(plan: Plan, settings: Settings, status: str = "", stale: bool = False) -> tuple[Row, ...]:
    """The full body of the readout: bosses first, then the waypoints and notes."""
    rows: list[Row] = []
    for boss in plan.rows:
        colour = settings.colour("big") if boss.is_big else settings.colour("list")
        rows.append(Row(boss_line(settings, boss), colour))
    for label, block in settings.waypoints:
        if plan.player is None:
            continue
        rows.append(Row(waypoint_line(label, block, Bearing.between(plan.player, block), settings),
                        settings.colour("note")))
    notes = ([status] if status else []) + list(plan.notes)
    for note in notes:
        rows.append(Row(note, settings.colour("note")))
    return tuple(rows)


def console_lines(plan: Plan, settings: Settings, status: str = "", stale: bool = False) -> list[str]:
    """The same readout as plain text, for a terminal and for the log file."""
    return [title_line(plan, settings)] + [f"  {row.text}" for row in
                                          rows_for(plan, settings, status, stale)]
