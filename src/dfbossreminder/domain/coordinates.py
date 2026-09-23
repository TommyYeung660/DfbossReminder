"""A set of watched map coordinates.

This started as the whitelist - the third requirement was a mode where only bosses at
coordinates the player named were shown - and the coordinate arithmetic outlived the
mode. The player dropped the filter on 2026-09-23 and asked for **styles** instead: the
same "one or more coordinates I care about" idea, applied to how a matching boss is
drawn rather than to whether it is drawn at all.

Two shapes cover how coordinates are actually used:

* an exact cell - ``1055,986`` - for a spot a boss is known to pass through;
* a cell with a radius - ``1055,986:2`` - for "this neighbourhood", so a whole corner of
  the map can be named with one entry instead of nine.

A radius is in **blocks** and measured with the same diagonal-aware count as the nearby
radius, so ``:1`` means the cell plus its eight neighbours.

The text form is what a settings file and a command line carry, so the parser is
deliberately forgiving about the separators (``;``, newline or ``,`` between cells) and
about surrounding whitespace, and strict about what a coordinate is: two integers,
nothing else. A typo becomes a reported parse error rather than a cell that silently
never matches.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Block, chebyshev

CELL_SEPARATORS = ";\n"
RADIUS_MARKER = ":"


@dataclass(frozen=True)
class CoordinateSet:
    """One watched cell, optionally widened to a radius of blocks."""

    block: Block
    radius: int = 0
    label: str = ""

    def contains(self, block: Block) -> bool:
        if self.radius <= 0:
            return self.block == block
        return chebyshev(self.block, block) <= self.radius

    def describe(self) -> str:
        text = str(self.block) if not self.radius else f"{self.block}:{self.radius}"
        return f"{text} ({self.label})" if self.label else text


class CoordinateError(ValueError):
    """Raised with the offending text so a bad settings file names itself."""


def parse_cell(text: str) -> CoordinateSet:
    """Parse one ``x,y`` or ``x,y:radius`` cell (a label may follow a ``=``)."""
    raw = text.strip()
    if not raw:
        raise CoordinateError("empty coordinate")
    label = ""
    if "=" in raw:
        raw, label = raw.split("=", 1)
        label = label.strip()
        raw = raw.strip()
    radius = 0
    if RADIUS_MARKER in raw:
        raw, radius_text = raw.split(RADIUS_MARKER, 1)
        try:
            radius = int(radius_text.strip())
        except ValueError as error:
            raise CoordinateError(f"bad radius in {text!r}") from error
        if radius < 0:
            raise CoordinateError(f"negative radius in {text!r}")
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise CoordinateError(f"a coordinate needs x,y: {text!r}")
    try:
        x, y = int(parts[0]), int(parts[1])
    except ValueError as error:
        raise CoordinateError(f"a coordinate needs two integers: {text!r}") from error
    return CoordinateSet(block=Block(x, y), radius=radius, label=label)


def parse_cells(value: str | list | tuple | None) -> tuple[CoordinateSet, ...]:
    """Every cell in a text blob, a list of strings, or a list of mappings.

    The settings file is JSON, so cells are stored as mappings and read back the same way
    a hand-typed string is parsed. Both paths produce the same objects, which is what
    keeps "it works from the file" and "it works from the command line" from being two
    different features.
    """
    if value is None:
        return ()
    cells: list[CoordinateSet] = []

    def add(text: str) -> None:
        cells.append(parse_cell(text))

    if isinstance(value, str):
        for chunk in _split(value):
            add(chunk)
        return tuple(cells)

    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                x, y = item.get("x"), item.get("y")
                if x is None or y is None:
                    raise CoordinateError(f"a coordinate needs x and y: {item!r}")
                try:
                    radius = int(item.get("radius", 0))
                except (TypeError, ValueError) as error:
                    raise CoordinateError(f"bad radius in {item!r}") from error
                if radius < 0:
                    raise CoordinateError(f"negative radius in {item!r}")
                label = str(item.get("label", ""))
                cells.append(CoordinateSet(block=Block(int(x), int(y)), radius=radius,
                                           label=label))
            elif isinstance(item, str):
                for chunk in _split(item):
                    add(chunk)
            else:
                raise CoordinateError(f"a coordinate must be a cell or a mapping: {item!r}")
        return tuple(cells)

    raise CoordinateError(f"coordinates must be text or a list: {value!r}")


def _split(text: str) -> list[str]:
    chunks = [text]
    for separator in CELL_SEPARATORS:
        chunks = [piece for chunk in chunks for piece in chunk.split(separator)]
    return [chunk for chunk in (piece.strip() for piece in chunks) if chunk]


def covers(cells: tuple[CoordinateSet, ...], block: Block) -> bool:
    """Whether any of these cells is this block."""
    return any(cell.contains(block) for cell in cells)


def to_dict(cells: tuple[CoordinateSet, ...]) -> list[dict]:
    """The JSON form, which round-trips through :func:`parse_cells`."""
    return [
        {"x": cell.block.x, "y": cell.block.y, "radius": cell.radius, "label": cell.label}
        for cell in cells
    ]
