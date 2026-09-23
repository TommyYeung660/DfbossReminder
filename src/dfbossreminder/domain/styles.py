"""Coordinate styles: draw a boss at the coordinates I name in my own colour.

The player's request (2026-09-23) was concrete: *"1015,999 and 1020,998, when there is a
boss, show it in red"*. So a style is a **set of cells plus how to draw them**, and the
set comes from :mod:`coordinates` - the same "one or more cells, optionally with a radius"
form that the deleted whitelist used, because that part of it was never the problem.

A rule is deliberately *not* a filter. The whitelist showed only the coordinates it
listed, which meant a style for one corner of the map would hide the rest of it; a style
only changes the colour of the rows it matches, and every boss keeps its place in the
list. Priority is style > big > ordinary, because a colour the player set by hand is a
stronger statement than the default.

Text form, for a command line or a hand-edited file::

    #FF3333=1015,999;1020,998        two cells, red
    #FFCC00=1057,1017:2              a cell and its eight neighbours, amber

The colour may also come first as a name from :data:`COLOUR_WORDS` (``red=…``), which is
there so the example the player gave works as written.
"""

from __future__ import annotations

from dataclasses import dataclass

from .colours import hex_to_rgb, normalize_colour
from .coordinates import CoordinateError, CoordinateSet, covers, parse_cells
from .coordinates import to_dict as cells_to_dict
from .geometry import Block


@dataclass(frozen=True)
class Highlight:
    """One style rule: these cells are drawn in this colour."""

    colour: str
    cells: tuple[CoordinateSet, ...]

    def matches(self, block: Block) -> bool:
        return covers(self.cells, block)

    def describe(self) -> str:
        where = ";".join(cell.describe() for cell in self.cells)
        return f"{self.colour}={where}"

    @property
    def rgb(self) -> tuple[int, int, int]:
        return hex_to_rgb(self.colour)


class StyleError(ValueError):
    """Raised with the offending text, so a bad rule names itself."""


def parse_highlight(text: str) -> Highlight:
    """Parse ``COLOUR=CELL[;CELL…]``, where COLOUR is ``#RRGGBB`` or a name."""
    raw = text.strip()
    if not raw:
        raise StyleError("empty style rule")
    if "=" not in raw:
        raise StyleError(f"a style rule needs a colour and a coordinate: {text!r}")
    colour_text, cells_text = raw.split("=", 1)
    colour = normalize_colour(colour_text)
    if not colour:
        raise StyleError(f"{colour_text.strip()!r} is neither a #RRGGBB colour nor a "
                         f"colour name, in {text!r}")
    try:
        cells = parse_cells(cells_text)
    except CoordinateError as error:
        raise StyleError(str(error)) from error
    if not cells:
        raise StyleError(f"a style rule needs at least one coordinate: {text!r}")
    return Highlight(colour=colour, cells=cells)


def parse_highlights(value: object) -> tuple[Highlight, ...]:
    """Every rule in a text blob, a list of strings, or a list of mappings.

    The settings file is JSON, so a rule is stored as ``{"colour": …, "cells": [...]}``
    and read back the same way a hand-typed ``--highlight`` string is parsed.
    """
    if value is None:
        return ()
    highlights: list[Highlight] = []

    if isinstance(value, str):
        for chunk in [piece.strip() for piece in value.split("|") if piece.strip()]:
            highlights.append(parse_highlight(chunk))
        return tuple(highlights)

    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                colour = normalize_colour(str(item.get("colour", "")))
                if not colour:
                    raise StyleError(f"a style rule needs a #RRGGBB colour or a colour "
                                     f"name: {item!r}")
                try:
                    cells = parse_cells(item.get("cells"))
                except CoordinateError as error:
                    raise StyleError(str(error)) from error
                if not cells:
                    raise StyleError(f"a style rule needs at least one coordinate: {item!r}")
                highlights.append(Highlight(colour=colour, cells=cells))
            elif isinstance(item, str):
                highlights.append(parse_highlight(item))
            else:
                raise StyleError(f"a style rule must be text or a mapping: {item!r}")
        return tuple(highlights)

    raise StyleError(f"styles must be text or a list: {value!r}")


def to_dict(highlights: tuple[Highlight, ...]) -> list[dict]:
    """The JSON form, which round-trips through :func:`parse_highlights`.

    The cells go out in the parsed shape rather than as their display text: a cell with a
    label describes itself as ``1055,986 (home)``, which is for a person to read and not
    something the parser would take back.
    """
    return [{"colour": highlight.colour, "cells": cells_to_dict(highlight.cells)}
            for highlight in highlights]


def colour_for(highlights: tuple[Highlight, ...], block: Block) -> str | None:
    """The colour of the first rule that matches, or None when nothing does.

    The first match wins rather than the most specific one: rules are ordered by the
    player, and an ordering the window shows and the readout follows is easier to reason
    about than a precedence rule that is invisible while you are editing it.
    """
    for highlight in highlights:
        if highlight.matches(block):
            return highlight.colour
    return None
