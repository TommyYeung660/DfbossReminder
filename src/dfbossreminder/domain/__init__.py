"""Pure decision logic: blocks, the boss map, coordinates and styles, settings, the plan.

Standard library only, no network, no clock, no Windows. Everything the player sees the
tool decide is decided here, which is what makes it testable on the development machine.
"""

from __future__ import annotations

from .bosses import BossEvent, Sighting, expand, parse_bossmap
from .colours import COLOUR_WORDS, hex_to_rgb, normalize_colour
from .coordinates import CoordinateError, CoordinateSet, covers, parse_cell, parse_cells
from .geometry import Bearing, Block, chebyshev, euclidean
from .plan import BossRow, Plan, build_plan, waypoint_rows
from .settings import Settings, normalize_user_id, parse_settings, to_dict
from .styles import Highlight, StyleError, colour_for, parse_highlight, parse_highlights

__all__ = [
    "Bearing",
    "Block",
    "BossEvent",
    "BossRow",
    "COLOUR_WORDS",
    "CoordinateError",
    "CoordinateSet",
    "Highlight",
    "Plan",
    "Settings",
    "Sighting",
    "StyleError",
    "build_plan",
    "chebyshev",
    "colour_for",
    "covers",
    "euclidean",
    "expand",
    "hex_to_rgb",
    "normalize_colour",
    "normalize_user_id",
    "parse_bossmap",
    "parse_cell",
    "parse_cells",
    "parse_highlight",
    "parse_highlights",
    "parse_settings",
    "to_dict",
    "waypoint_rows",
]
