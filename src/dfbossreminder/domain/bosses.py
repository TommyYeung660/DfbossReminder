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

# A boss name carries its own count, e.g. "6 x Bandits" or "1 x Devil Hound". The digits are
# captured as well as matched: ``strip_count`` removes the prefix and ``boss_count`` reads it.
_COUNT_PREFIX = re.compile(r"^\s*(\d+)\s*x\s*", re.IGNORECASE)

TIER_NORMAL = "normal"
TIER_BIG = "big"

# The map *does* say which spawn is a special one, just not in a field called "tier": it says
# it in the length of the window. Measured on 2026-10-07 across a whole payload (50 entries):
#
#     1.00 h   26 entries   the city cycles, one per zone
#     2.00 h    8 entries   the special daily group spawns ("1 x Evolved Longarms + ...")
#     3.00 h    1 entry     "1 x Devil Hound" at 1056,991 with a single block
#     0.08 h    2 entries   short special spawns (Six-Armed Bandit)
#
# So the rule is the player's own, in two steps on 2026-10-07:
#
#   "有些Special Daily 是2小時的, 將規則簡化為大於一小時的boss 不受半徑限制即可"
#   "2小時的 boss 群不應該當是ultra boss, 也要受半徑限制"
#
# - a window longer than an hour (threshold 1.5 h, inside the empty band between 1 h and 2 h, so
#   neither a city cycle nor a daily can flip sides over a few minutes of drift), **and**
# - a spawn of exactly one boss. The 2 h band is where the *groups* live: seven of its eight live
#   entries spawn several different bosses in one event ("1 x Flaming Zombie<br />2 x Riot Shield
#   Guy") and one spawns four of the same ("4 x Flaming Zombie"). A Special Daily is a single
#   boss - one Devil Hound, one Behemoth - which is what makes it worth a row from anywhere.
#
# This replaced two earlier attempts that both used a *name* list, and both were wrong in the
# same way: a name is not an identity. On 2026-10-07 the map carried three `1 x Devil Hound`
# entries at once - one daily (3 h, one block) and two ordinary city-cycle spawns of the same
# enemy (1 h, ten and twelve blocks) - so a name test put two rows for a boss forty blocks away
# at the top of the readout while the real one was missing (the player: "1056 X 991 的 Devil
# Hound 才要顯示, 其他地方是同名但非 ultra boss, json 數據應該有分別").
DAILY_WINDOW_MINUTES = 90.0


def strip_count(name: str) -> str:
    """``"1 x Devil Hound"`` -> ``"Devil Hound"``.

    The big-boss readout names the boss rather than its group size, and the boss map
    always ships the count prefix, so the prefix is removed per segment (one name
    can list two bosses joined by ``+``).
    """
    return " + ".join(_COUNT_PREFIX.sub("", segment).strip() for segment in name.split("+"))


def boss_count(name: str) -> int:
    """How many bosses this one event spawns, read from the name the map publishes.

    The map carries the count per boss inside the name - ``"4 x Flaming Zombie"`` is four,
    ``"1 x Flaming Zombie + 2 x Riot Shield Guy"`` is three, and a name with no count prefix
    (a mission's, say) is one. Segments arrive joined by ``" + "`` because the payload separates
    them with ``<br />``, so this is also how a *group* of different bosses is recognised.
    """
    total = 0
    for segment in name.split("+"):
        match = _COUNT_PREFIX.match(segment)
        total += int(match.group(1)) if match else 1
    return max(1, total)


def tier_of(event: BossEvent) -> str:
    """Whether this spawn is a special (big/ultra) boss: a **single boss** on a **long window**.

    Nothing else is consulted - no name, no setting - because the map's own timings and counts
    already say which spawns are the special ones. Every attempt to name them was wrong in the
    same way, and a name is not an identity: see ``DAILY_WINDOW_MINUTES``.
    """
    if event.is_mission or event.duration_minutes <= DAILY_WINDOW_MINUTES:
        return TIER_NORMAL
    return TIER_BIG if boss_count(event.name) == 1 else TIER_NORMAL


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
    def cycle_key(self) -> tuple[str, float]:
        """What makes this spawn *this* spawn, rather than the next one.

        The box column hides a boss by this key, and the player's rule for that is that a
        dismissal must not survive into the next cycle. So the key is the game's own entry
        id **together with the cycle's start time**, which is what changes when the boss
        spawns again.

        Neither half alone is enough. The name is not an identity: the live map carries two
        separate ``"2 x Bandits"`` events at once, in different places, so hiding by name
        would take out a boss the player never pointed at. And the end time is not one
        either: the map is a third party's feed and may extend a live window, which would
        make a hidden boss reappear in the middle of its own cycle. The start time of a
        spawn does not move while the spawn is live.
        """
        return (self.game_id, self.start)

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

    @property
    def cycle_key(self) -> tuple[str, float]:
        """The spawn this sighting belongs to, so hiding one row can hide its siblings.

        A single boss event lists every block it can be at - the live map's ``6 x Bandits``
        had three - and the readout shows one row per block. The player pointed at one of
        those rows and asked for the *related* ones to go too, which is exactly this key:
        same spawn. A different spawn that happens to share the name keeps its rows.
        """
        return self.event.cycle_key


def expand(events: list[BossEvent]) -> list[Sighting]:
    """One sighting per (event, block) pair, in a stable order."""
    return [Sighting(event=event, block=block) for event in events for block in event.blocks]
