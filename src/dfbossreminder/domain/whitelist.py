"""The coordinate whitelist.

The player's third requirement is a mode where only bosses at coordinates they
care about are shown at all. Two shapes cover how that is actually used:

* an exact cell - ``1055,986`` - for a spot a boss is known to pass through;
* a cell with a radius - ``1055,986:2`` - for "this neighbourhood", so a whole
  corner of the map can be watched with one entry instead of nine.

A radius is in **blocks** and measured with the same diagonal-aware count as the
nearby radius, so ``:1`` means the entry plus its eight neighbours.

The text form is what a settings file and a command line carry, so the parser is
deliberately forgiving about the separators (``;``, newline or ``,`` between
entries) and about surrounding whitespace, and strict about what a coordinate is:
two integers, nothing else. A typo becomes a reported parse error rather than a
whitelist entry that silently never matches.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import Block, chebyshev

ENTRY_SEPARATORS = ";\n"
RADIUS_MARKER = ":"


@dataclass(frozen=True)
class WhitelistEntry:
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


class WhitelistError(ValueError):
    """Raised with the offending text so a bad settings file names itself."""


def parse_entry(text: str) -> WhitelistEntry:
    """Parse one ``x,y`` or ``x,y:radius`` entry (a label may follow a ``=``)."""
    raw = text.strip()
    if not raw:
        raise WhitelistError("empty whitelist entry")
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
            raise WhitelistError(f"bad radius in {text!r}") from error
        if radius < 0:
            raise WhitelistError(f"negative radius in {text!r}")
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2:
        raise WhitelistError(f"a whitelist entry needs x,y: {text!r}")
    try:
        x, y = int(parts[0]), int(parts[1])
    except ValueError as error:
        raise WhitelistError(f"a whitelist entry needs two integers: {text!r}") from error
    return WhitelistEntry(block=Block(x, y), radius=radius, label=label)


def parse_whitelist(value: str | list | tuple | None) -> tuple[WhitelistEntry, ...]:
    """Every entry in a text blob, a list of strings, or a list of dicts.

    The settings file is JSON, so entries are stored as dicts and read back the
    same way a hand-typed ``--whitelist`` string is parsed. Both paths produce the
    same objects, which is what keeps "it works from the file" and "it works from
    the command line" from being two different features.
    """
    if value is None:
        return ()
    entries: list[WhitelistEntry] = []

    def add(text: str) -> None:
        entries.append(parse_entry(text))

    if isinstance(value, str):
        for chunk in _split(value):
            add(chunk)
        return tuple(entries)

    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, dict):
                x, y = item.get("x"), item.get("y")
                if x is None or y is None:
                    raise WhitelistError(f"a whitelist entry needs x and y: {item!r}")
                try:
                    radius = int(item.get("radius", 0))
                except (TypeError, ValueError) as error:
                    raise WhitelistError(f"bad radius in {item!r}") from error
                if radius < 0:
                    raise WhitelistError(f"negative radius in {item!r}")
                label = str(item.get("label", ""))
                entries.append(WhitelistEntry(block=Block(int(x), int(y)), radius=radius, label=label))
            elif isinstance(item, str):
                for chunk in _split(item):
                    add(chunk)
            else:
                raise WhitelistError(f"a whitelist entry must be a coordinate or a mapping: {item!r}")
        return tuple(entries)

    raise WhitelistError(f"a whitelist must be text or a list: {value!r}")


def _split(text: str) -> list[str]:
    chunks = [text]
    for separator in ENTRY_SEPARATORS:
        chunks = [piece for chunk in chunks for piece in chunk.split(separator)]
    return [chunk for chunk in (piece.strip() for piece in chunks) if chunk]


def allows(entries: tuple[WhitelistEntry, ...], block: Block) -> bool:
    """Whether any whitelist entry covers this block."""
    return any(entry.contains(block) for entry in entries)


def allows_any(entries: tuple[WhitelistEntry, ...], blocks: tuple[Block, ...]) -> bool:
    """Whether a boss with these spawn blocks is anywhere on the whitelist.

    A boss event with several locations is allowed when *any* of them is watched,
    because the player wants to know that a boss they care about is out.
    """
    return any(allows(entries, block) for block in blocks)


def to_dict(entries: tuple[WhitelistEntry, ...]) -> list[dict]:
    """The JSON form, which round-trips through :func:`parse_whitelist`."""
    return [
        {"x": entry.block.x, "y": entry.block.y, "radius": entry.radius, "label": entry.label}
        for entry in entries
    ]
