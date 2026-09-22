"""Pure decision logic: blocks, the boss map, the whitelist, settings, the plan.

Standard library only, no network, no clock, no Windows. Everything the player
sees the tool decide is decided here, which is what makes it testable on the
development machine.
"""

from __future__ import annotations

from .bosses import BossEvent, Sighting, expand, parse_bossmap
from .geometry import Bearing, Block, chebyshev, euclidean
from .plan import BossRow, Plan, build_plan, waypoint_rows
from .settings import Settings, normalize_user_id, parse_settings, to_dict
from .whitelist import (
    WhitelistEntry,
    WhitelistError,
    allows,
    allows_any,
    parse_entry,
    parse_whitelist,
)

__all__ = [
    "Bearing",
    "Block",
    "BossEvent",
    "BossRow",
    "Plan",
    "Settings",
    "Sighting",
    "WhitelistEntry",
    "WhitelistError",
    "allows",
    "allows_any",
    "build_plan",
    "chebyshev",
    "euclidean",
    "expand",
    "normalize_user_id",
    "parse_bossmap",
    "parse_entry",
    "parse_settings",
    "parse_whitelist",
    "to_dict",
    "waypoint_rows",
]
