"""Presentation: the overlay window, its placement arithmetic, and the text rows.

``layout`` and ``view`` are pure and run anywhere. ``panel`` touches Windows and
binds its API inside a function, so importing this package never fails on a Mac.
"""

from __future__ import annotations

from .layout import ANCHORS, place, place_below_minimap
from .panel import Overlay, Row, anchored_overlay
from .view import (
    console_lines,
    rows_for,
    title_line,
)

__all__ = [
    "ANCHORS",
    "Overlay",
    "Row",
    "anchored_overlay",
    "console_lines",
    "place",
    "place_below_minimap",
    "rows_for",
    "title_line",
]
