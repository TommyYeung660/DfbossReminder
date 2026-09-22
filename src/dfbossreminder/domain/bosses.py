"""Parsing and filtering of the dfprofiler boss map.

``https://www.dfprofiler.com/bossmap/json/`` returns a JSON object keyed by an
event index, where each value describes one event. An event is treated as a boss
spawn when it names a special enemy and carries at least one location; the fields
that matter are:

| field | meaning |
| --- | --- |
| ``locations`` | list of ``["x", "y"]`` **strings**, the map blocks the boss is at |
| ``special_enemy_type`` | the boss's display name, sometimes with ``<br />`` separators |
| ``special_enemy_amount`` | how many of them spawn at that location |
| ``boss_num`` | non-zero for a boss cycle entry, ``0`` for a mission |
| ``event_type`` | ``"mission"`` for a mission, empty for a boss cycle |
| ``start_time`` / ``end_time`` | unix seconds |
| ``title`` | the mission's title, or empty |

Nothing here guesses. An event whose ``end_time`` is in the past is dropped
because the client no longer spawns it, and an entry whose fields are the wrong
shape is skipped rather than repaired - the boss map is a third party's output and
a change in it must show up as "fewer bosses found", not as a wrong coordinate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .geometry import Block

_MISSION = "mission"

# The boss map uses "<br />" inside a name to list several bosses spawning
# together; the panel wants one readable line per entry.
_BREAK = re.compile(r"\s*<br\s*/?>\s*", re.IGNORECASE)

# A boss name carries its own count, e.g. "6 x Bandits" or "1 x Devil Hound".
_COUNT_PREFIX = re.compile(r"^\s*\d+\s*x\s*", re.IGNORECASE)

# The bosses the wiki calls "Special Daily Bosses": extra tough, one spawn a day,
# up to three hours instead of the normal one, and they drop crafting materials.
# They are the default for the big-boss readout, which shows the end time rather
# than a bearing - a three-hour window is worth knowing, where a city-cycle boss is
# one you walk to now.
#
# This is a **name list, not a field**: the boss map publishes no tier, so the tier
# has to be configured. These three are the wiki's list; a player who counts
# something else as big (the Raven Ridge or Wasteland bosses, say) adds the name in
# the settings window.
DEFAULT_BIG_BOSSES: tuple[str, ...] = ("Devil Hound", "Volatile Leaper", "Behemoth")

TIER_NORMAL = "normal"
TIER_BIG = "big"


def strip_count(name: str) -> str:
    """``"1 x Devil Hound"`` -> ``"Devil Hound"``.

    The big-boss readout names the boss rather than its group size, and the boss map
    always ships the count prefix, so the prefix is removed per segment (one name
    can list two bosses joined by ``+``).
    """
    return " + ".join(_COUNT_PREFIX.sub("", segment).strip() for segment in name.split("+"))


def tier_of(name: str, big_bosses: tuple[str, ...]) -> str:
    """Whether this boss is one of the configured big/ultra bosses.

    Matching is on the name **without** its count prefix and is case-insensitive, so
    ``"1 x Devil Hound"`` matches the configured ``"Devil Hound"``, and a client that
    changes the count does not silently drop the boss out of the tier.
    """
    wanted = {value.strip().lower() for value in big_bosses if value.strip()}
    if not wanted:
        return TIER_NORMAL
    for segment in strip_count(name).split("+"):
        if segment.strip().lower() in wanted:
            return TIER_BIG
    return TIER_NORMAL


def _clean_name(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return re.sub(r"\s+", " ", _BREAK.sub(" + ", raw)).strip()


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class BossEvent:
    """One boss spawn, as the boss map describes it."""

    game_id: str
    name: str
    amount: int
    blocks: tuple[Block, ...]
    start: float
    end: float
    boss_num: int = 0
    event_type: str = ""
    title: str = ""

    @property
    def is_mission(self) -> bool:
        return self.event_type.strip().lower() == _MISSION

    @property
    def duration_minutes(self) -> float:
        return (self.end - self.start) / 60.0

    def minutes_left(self, now: float) -> float:
        return (self.end - now) / 60.0

    def expires_within(self, now: float, minutes: float) -> bool:
        return self.minutes_left(now) <= minutes


def parse_bossmap(
    payload: object,
    now: float,
    include_missions: bool = False,
) -> list[BossEvent]:
    """Every live boss spawn in a boss-map payload, newest expiry last.

    ``now`` is passed in rather than read from the clock so the rule "an expired
    boss is not shown" can be tested, and so one plan is built from one instant.
    """
    if not isinstance(payload, dict):
        return []
    events: list[BossEvent] = []
    for key, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        name = _clean_name(raw.get("special_enemy_type"))
        if not name or name == "0":
            continue
        locations = raw.get("locations")
        if not isinstance(locations, list) or not locations:
            continue
        blocks: list[Block] = []
        for entry in locations:
            # A location is a two-element list of numeric strings. Anything else
            # (a missing pair, a nested object) is not a coordinate and is dropped.
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            x, y = _to_int(entry[0]), _to_int(entry[1])
            if x is None or y is None:
                continue
            block = Block(x, y)
            if block not in blocks:
                blocks.append(block)
        if not blocks:
            continue
        end = _to_float(raw.get("end_time"))
        if end is None or end <= now:
            continue
        start = _to_float(raw.get("start_time"))
        if start is None:
            start = end
        event_type = raw.get("event_type") if isinstance(raw.get("event_type"), str) else ""
        if event_type.strip().lower() == _MISSION and not include_missions:
            continue
        amount = _to_int(raw.get("special_enemy_amount")) or 0
        boss_num = _to_int(raw.get("boss_num")) or 0
        title = raw.get("title") if isinstance(raw.get("title"), str) else ""
        events.append(
            BossEvent(
                game_id=str(raw.get("game_id", key)),
                name=name,
                amount=amount,
                blocks=tuple(blocks),
                start=start,
                end=end,
                boss_num=boss_num,
                event_type=event_type,
                title=title,
            )
        )
    events.sort(key=lambda event: (event.end, event.name, event.game_id))
    return events


@dataclass(frozen=True)
class Sighting:
    """One boss, at one block - the unit the radius and whitelist tests work on.

    A single boss event can list dozens of locations (a 60-minute city boss cycle
    lists one per block it can spawn in), so the event is expanded before any
    distance test: the player is near a *place*, not near an event.
    """

    event: BossEvent
    block: Block

    @property
    def name(self) -> str:
        return self.event.name

    @property
    def amount(self) -> int:
        return self.event.amount

    @property
    def is_mission(self) -> bool:
        return self.event.is_mission


def expand(events: list[BossEvent]) -> list[Sighting]:
    """One sighting per (event, block) pair, in a stable order."""
    return [Sighting(event=event, block=block) for event in events for block in event.blocks]
