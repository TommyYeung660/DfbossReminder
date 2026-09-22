"""The display plan: which bosses to show, in what order, as what text.

This is the whole of the tool's decision-making, and it is a pure function of
(boss events, player block, settings, now). Nothing here draws, fetches, or reads
the clock, so the rules the player sees - "within N blocks", "only on the
whitelist", "nearest first", "very close is emphasised" - are tested without a
game, a network, or Windows.

The plan also says *why* it looks the way it does in ``notes``, because a bare
list of rows cannot be told apart from a broken one. "no player position" and
"radius 8 blocks" and "12 more beyond the radius" are the difference between an
empty panel being correct and being a bug.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .bosses import TIER_NORMAL, Sighting, expand, strip_count, tier_of
from .geometry import Bearing, Block, euclidean
from .settings import Settings
from .whitelist import allows_any

NO_PLAYER = "no player position"


@dataclass(frozen=True)
class BossRow:
    """One boss at one place, ready to be drawn as a line."""

    name: str
    block: Block
    amount: int
    is_mission: bool
    distance: int | None
    bearing: Bearing | None
    minutes_left: float
    whitelisted: bool
    tier: str = TIER_NORMAL
    end_epoch: float = 0.0

    @property
    def is_big(self) -> bool:
        return self.tier != TIER_NORMAL

    @property
    def short_name(self) -> str:
        """The boss without its group count, for the big-boss readout."""
        return strip_count(self.name)

    def direction(self, style: str = "compact") -> str:
        """The bearing, as the compact HUD form (``5LD1``) unless asked otherwise.

        The readout is a narrow strip beside the map, so the compact form is the
        default; ``style="zh"`` or ``"en"`` gives the longer words for the console
        and the log, where there is room for them.
        """
        if self.bearing is None:
            return "?"
        if style == "compact":
            return self.bearing.compact()
        return self.bearing.describe(style)

    def end_clock(self) -> str:
        """The boss's expiry as local wall-clock ``HH:MM``.

        Local time on purpose: the player reads it off their own clock, and the boss
        map's timestamps are unix seconds.
        """
        if not self.end_epoch:
            return "--:--"
        return time.strftime("%H:%M", time.localtime(self.end_epoch))


@dataclass(frozen=True)
class Plan:
    """The rows to draw, plus what the plan could not include and why."""

    rows: tuple[BossRow, ...]
    player: Block | None
    notes: tuple[str, ...]
    total_sightings: int
    nearby_sightings: int
    shown: int
    suppressed_by_whitelist: int
    beyond_radius: int

    @property
    def empty(self) -> bool:
        return not self.rows


def _row(
    sighting: Sighting,
    player: Block | None,
    whitelisted: bool,
    now: float,
    big_bosses: tuple[str, ...],
) -> BossRow:
    bearing = Bearing.between(player, sighting.block) if player else None
    return BossRow(
        name=sighting.name,
        block=sighting.block,
        amount=sighting.amount,
        is_mission=sighting.is_mission,
        distance=bearing.blocks if bearing else None,
        bearing=bearing,
        minutes_left=sighting.event.minutes_left(now),
        whitelisted=whitelisted,
        tier=tier_of(sighting.name, big_bosses),
        end_epoch=sighting.event.end,
    )


def build_plan(
    events: list,
    player: Block | None,
    settings: Settings,
    now: float,
) -> Plan:
    """Decide the rows, applying the whitelist first and otherwise the radius.

    In whitelist mode the whitelist *is* the filter: a watched coordinate is
    reported wherever the player is, which is the whole point of watching one. The
    radius only applies in the normal mode, where the question is "what is near me".
    """
    sightings = expand(events)
    notes: list[str] = []

    whitelisted_only = settings.whitelist_mode
    if whitelisted_only and not settings.whitelist:
        # Whitelist mode with nothing on the list means nothing can match. Showing
        # everything instead would be the opposite of what the mode is for, so this
        # stays empty and says why.
        notes.append("whitelist mode is on but the whitelist is empty")

    suppressed = 0
    beyond = 0
    considered: list[BossRow] = []
    for sighting in sightings:
        if whitelisted_only and not allows_any(settings.whitelist, (sighting.block,)):
            suppressed += 1
            continue
        considered.append(_row(sighting, player, whitelisted_only, now, settings.big_bosses))

    if whitelisted_only:
        chosen = considered if settings.whitelist else []
        notes.append(f"whitelist on ({len(settings.whitelist)} entries, {suppressed} suppressed)")
        if player is None:
            notes.append(NO_PLAYER)
    elif player is None:
        # No position means no radius to measure. Listing everything at least names
        # the bosses that are out, and the note keeps that from looking deliberate.
        notes.append(NO_PLAYER)
        chosen = considered if settings.show_all_without_player else []
    else:
        chosen = []
        for row in considered:
            if row.distance is not None and row.distance <= settings.radius_blocks:
                chosen.append(row)
            else:
                beyond += 1
        notes.append(f"within {settings.radius_blocks} blocks")

    # Nearest first; the straight-line distance only breaks ties between cells that
    # are the same number of blocks away, so the order never contradicts the count.
    chosen.sort(key=lambda row: (0 if row.is_big else 1,
                                 row.distance if row.distance is not None else 1 << 30,
                                 euclidean(player, row.block) if player else 0.0,
                                 row.name,
                                 row.block.y, row.block.x))

    if settings.include_missions:
        notes.append("missions included")
    if beyond:
        notes.append(f"{beyond} beyond the radius")

    shown = chosen[: settings.max_rows]
    if len(chosen) > len(shown):
        notes.append(f"{len(chosen) - len(shown)} more not shown")

    return Plan(
        rows=tuple(shown),
        player=player,
        notes=tuple(notes),
        total_sightings=len(sightings),
        nearby_sightings=len(chosen),
        shown=len(shown),
        suppressed_by_whitelist=suppressed if whitelisted_only else 0,
        beyond_radius=beyond,
    )


def waypoint_rows(settings: Settings, player: Block | None, style: str = "zh") -> list[tuple[str, str]]:
    """The always-known places, as ``(label, bearing)`` pairs.

    ``Secronom Bunker`` is the default one: a boss run ends by walking home, and
    knowing the bearing back is the one thing that is useful with no bosses around.
    """
    rows: list[tuple[str, str]] = []
    if player is None:
        return rows
    for label, block in settings.waypoints:
        rows.append((label, Bearing.between(player, block).describe(style)))
    return rows
