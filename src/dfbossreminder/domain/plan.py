"""The display plan: which bosses to show, in what order, as what text.

This is the whole of the tool's decision-making, and it is a pure function of
(boss events, player block, settings, now). Nothing here draws, fetches, or reads
the clock, so the rules the player sees - "within N blocks", "nearest first",
"big bosses first", "capped at N" - are tested without a game, a network, or
Windows.

The plan also says *why* it looks the way it does in ``notes``, because a bare
list of rows cannot be told apart from a broken one. "no player position" and
"radius 8 blocks" and "12 more beyond the radius" are the difference between an
empty panel being correct and being a bug. A note carries a code and its values, not
a sentence: the wording belongs to the presentation, which is what lets the readout
be Chinese without teaching the domain a language.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .bosses import TIER_NORMAL, Sighting, expand, strip_count, tier_of
from .geometry import Bearing, Block, euclidean
from .settings import Settings

NO_PLAYER = "no_player"


@dataclass(frozen=True)
class Note:
    """Why the plan looks the way it does, as a code rather than a sentence.

    A note is shown to the player, and the player reads Chinese; keeping the wording
    out of here means the domain stays language-neutral and the presentation picks the
    words. ``args`` is a tuple of pairs so the value stays hashable and comparable.
    """

    code: str
    args: tuple[tuple[str, object], ...] = ()

    def __str__(self) -> str:
        return self.code + ("(" + ", ".join(f"{k}={v}" for k, v in self.args) + ")" if self.args else "")

    def values(self) -> dict:
        return dict(self.args)


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
    notes: tuple[Note, ...]
    total_sightings: int
    nearby_sightings: int
    shown: int
    beyond_radius: int

    @property
    def empty(self) -> bool:
        return not self.rows


def _row(
    sighting: Sighting,
    player: Block | None,
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
        tier=tier_of(sighting.name, big_bosses),
        end_epoch=sighting.event.end,
    )


def build_plan(
    events: list,
    player: Block | None,
    settings: Settings,
    now: float,
) -> Plan:
    """Decide the rows: everything within the radius, nearest first.

    There is no filter any more. The player's third requirement started as a whitelist
    that *hid* everything else; on 2026-09-23 they replaced it with coordinate styles,
    which colour a matching boss instead of removing the rest. So the only question here
    is the radius one - "what is near me" - and ``settings.highlights`` never changes
    which rows exist, only how the view draws them.
    """
    sightings = expand(events)
    notes: list[Note] = []

    beyond = 0
    considered: list[BossRow] = [
        _row(sighting, player, now, settings.big_bosses) for sighting in sightings
    ]

    if player is None:
        # No position means no radius to measure. Listing everything at least names
        # the bosses that are out, and the note keeps that from looking deliberate.
        notes.append(Note(NO_PLAYER))
        chosen = considered if settings.show_all_without_player else []
    else:
        chosen = []
        for row in considered:
            if row.distance is not None and row.distance <= settings.radius_blocks:
                chosen.append(row)
            else:
                beyond += 1
        notes.append(Note("within", (("radius", settings.radius_blocks),)))

    # Nearest first; the straight-line distance only breaks ties between cells that
    # are the same number of blocks away, so the order never contradicts the count.
    chosen.sort(key=lambda row: (0 if row.is_big else 1,
                                 row.distance if row.distance is not None else 1 << 30,
                                 euclidean(player, row.block) if player else 0.0,
                                 row.name,
                                 row.block.y, row.block.x))

    styled = sum(1 for row in chosen if settings.style_colour(row.block))
    if settings.highlights:
        # Reported even when nothing matched: "why is it not red?" is answered by
        # seeing that the rule is loaded and that no boss is standing on it.
        notes.append(Note("styles", (("rules", len(settings.highlights)), ("matched", styled))))
    if settings.include_missions:
        notes.append(Note("missions"))
    if beyond:
        notes.append(Note("beyond", (("count", beyond),)))

    shown = chosen[: settings.max_rows]
    if len(chosen) > len(shown):
        notes.append(Note("capped", (("count", len(chosen) - len(shown)),)))

    return Plan(
        rows=tuple(shown),
        player=player,
        notes=tuple(notes),
        total_sightings=len(sightings),
        nearby_sightings=len(chosen),
        shown=len(shown),
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
