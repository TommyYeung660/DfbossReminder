"""Block arithmetic for the Dead Frontier map.

Every distance this project reports is measured in **blocks**, the unit the game's
own map uses. That is not a style choice: the profiler's boss map lists a boss by
``["1055", "987"]`` and a profile's ``gpscoords`` is ``["1057", "1017"]``, both in
this same grid, so the two are directly comparable.

The client's own world position is *not* comparable with a map coordinate. The
in-memory player position is local to whatever block the player is standing in
(measured live: world ``(48.27, 38.89)`` while the map read ``1057 x 1017``), so
adding or subtracting the two would be meaningless. This module therefore knows
only blocks, and nothing here ever sees a world unit.

Axis convention, taken from the game's own boss-map table where the row for
``y981`` is drawn above the row for ``y990``: ``+x`` is east (right on the map)
and ``+y`` is south (down). The direction words match the ones the previous tool
printed and the player read, so a bearing still reads the same way.
"""

from __future__ import annotations

from dataclasses import dataclass

# A district is fought through 8-way, so the number of blocks to cross is the
# larger of the two axis gaps, not their hypotenuse.
EAST = "E"
WEST = "W"
NORTH = "N"
SOUTH = "S"


@dataclass(frozen=True, order=True)
class Block:
    """One map cell, as the profiler and the in-game minimap print it."""

    x: int
    y: int

    def __str__(self) -> str:
        return f"{self.x},{self.y}"


def chebyshev(a: Block, b: Block) -> int:
    """How many blocks separate two cells when you may move diagonally.

    This is the "blocks away" a player counts while walking, which is why it is
    the radius test rather than the straight-line distance.
    """
    return max(abs(a.x - b.x), abs(a.y - b.y))


def euclidean(a: Block, b: Block) -> float:
    """Straight-line block distance, used only to order rows of equal reach."""
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


@dataclass(frozen=True)
class Bearing:
    """Where a target is relative to the player, in blocks."""

    dx: int
    dy: int

    @classmethod
    def between(cls, player: Block, target: Block) -> "Bearing":
        return cls(target.x - player.x, target.y - player.y)

    @property
    def blocks(self) -> int:
        """Blocks to cross: the same count :func:`chebyshev` gives."""
        return max(abs(self.dx), abs(self.dy))

    @property
    def vertical(self) -> str:
        return NORTH if self.dy < 0 else SOUTH if self.dy > 0 else ""

    @property
    def horizontal(self) -> str:
        return EAST if self.dx > 0 else WEST if self.dx < 0 else ""

    def compact(self) -> str:
        """The HUD bearing: ``5LD1`` is five blocks left and one down.

        Horizontal comes first, then vertical, each with its count, and a count of
        zero is omitted. A boss standing at the player's own block reads ``0``.
        This is the form the readout uses, and it is deliberately derivable: the
        player's own block minus the boss's gives the two numbers directly, which is
        how the format was confirmed against a hand-written example
        (``1057,1017`` -> ``1052,1018`` = ``5LD1``).
        """
        parts: list[str] = []
        if self.dx:
            parts.append(f"{abs(self.dx)}{'R' if self.dx > 0 else 'L'}")
        if self.dy:
            parts.append(f"{'D' if self.dy > 0 else 'U'}{abs(self.dy)}")
        return "".join(parts) if parts else "0"

    def describe(self, style: str = "zh", separator: str = "") -> str:
        """A short, readable bearing such as ``3右2上`` or ``E3 N2``.

        The default is the zh form because that is how the player reads it, and
        the previous tool printed it. ``style="en"`` gives ``E3 N2`` for a log or
        a bug report, where the double-width characters are awkward.
        """
        parts: list[str] = []
        if style == "en":
            if self.dx:
                parts.append(f"{'E' if self.dx > 0 else 'W'}{abs(self.dx)}")
            if self.dy:
                parts.append(f"{'S' if self.dy > 0 else 'N'}{abs(self.dy)}")
        else:
            if self.dx:
                parts.append(f"{abs(self.dx)}{'右' if self.dx > 0 else '左'}")
            if self.dy:
                parts.append(f"{abs(self.dy)}{'下' if self.dy > 0 else '上'}")
        if not parts:
            return "同格" if style != "en" else "here"
        return separator.join(parts)
