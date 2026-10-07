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
from collections.abc import Container
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
    # Which spawn this row belongs to. Two rows of the same boss at two blocks share it,
    # which is what makes "hide the related rows" a matter of comparing keys.
    cycle_key: tuple[str, float] = ("", 0.0)

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


def _row(sighting: Sighting, player: Block | None, now: float) -> BossRow:
    bearing = Bearing.between(player, sighting.block) if player else None
    return BossRow(
        name=sighting.name,
        block=sighting.block,
        amount=sighting.amount,
        is_mission=sighting.is_mission,
        distance=bearing.blocks if bearing else None,
        bearing=bearing,
        minutes_left=sighting.event.minutes_left(now),
        # The spawn's own window decides the tier: see tier_of.
        tier=tier_of(sighting.event.duration_minutes),
        end_epoch=sighting.event.end,
        cycle_key=sighting.cycle_key,
    )


def build_plan(
    events: list,
    player: Block | None,
    settings: Settings,
    now: float,
    dismissed: Container = frozenset(),
) -> Plan:
    """Decide the rows: everything within the radius, plus every big boss, nearest first.

    There is no filter any more. The player's third requirement started as a whitelist
    that *hid* everything else; on 2026-09-23 they replaced it with coordinate styles,
    which colour a matching boss instead of removing the rest. So for an ordinary boss the
    only question here is the radius one - "what is near me" - and ``settings.highlights``
    never changes which rows exist, only how the view draws them.

    **A big boss is never hidden by the radius** (the player, 2026-10-07: "ultra boss 無法
    顯示, 應該是不受距離限制的"). The tier is a configured name list, and these are the
    bosses worth crossing the map for, so a live one is always worth a row - what the row
    gives is not a bearing but the time its window closes. Two details keep that from
    flooding the readout:

    * an event that lists several blocks contributes the rows it would have contributed
      inside the radius, and **one** row when none of its blocks is inside it - the nearest
      one. The live map's ``1 x Devil Hound`` listed twelve blocks in one small region, and
      twelve near-identical rows forty blocks away is not information;
    * with no player position there is no distance to be exempt from, so nothing changes:
      that case is the ``show_all_without_player`` setting's to decide.

    ``dismissed`` is the one thing that *does* remove rows, and it is not a filter in that
    sense: it is the box column's state, one tick at a time, and it is dropped at the end
    of the cycle by ``domain.dismissed``. Dismissed rows are taken out *before* the radius
    test, so a boss the player has put away is not also counted as "beyond the radius" -
    one row must not be reported twice, in two counts that mean different things.
    """
    sightings = expand(events)
    notes: list[Note] = []

    beyond = 0
    considered: list[BossRow] = [
        _row(sighting, player, now) for sighting in sightings
    ]
    put_away = [row for row in considered if row.cycle_key in dismissed]
    if put_away:
        # Named as bosses *and* rows: the player ticked one box and several lines went, and
        # both numbers are true - saying only "1 hidden" looks like a broken count when
        # four lines left the screen.
        notes.append(Note("dismissed", (("bosses", len({row.cycle_key for row in put_away})),
                                        ("rows", len(put_away)))))
    considered = [row for row in considered if row.cycle_key not in dismissed]

    far_big: list[BossRow] = []
    if player is None:
        # No position means no radius to measure. Listing everything at least names
        # the bosses that are out, and the note keeps that from looking deliberate.
        notes.append(Note(NO_PLAYER))
        chosen = considered if settings.show_all_without_player else []
    else:
        chosen = []
        nearest_out_of_range: dict[tuple, BossRow] = {}
        for row in considered:
            if row.distance is not None and row.distance <= settings.radius_blocks:
                chosen.append(row)
            elif row.is_big:
                # Out of range and big: keep only the closest block of each such event, so
                # one distant boss is one row however many places the feed lists for it.
                best = nearest_out_of_range.get(row.cycle_key)
                if best is None or (row.distance or 0) < (best.distance or 0):
                    nearest_out_of_range[row.cycle_key] = row
            else:
                beyond += 1
        # An event with a block inside the radius already has its rows; it must not get a
        # second row out of the fallback as well.
        in_range = {row.cycle_key for row in chosen}
        far_big = [row for key, row in nearest_out_of_range.items() if key not in in_range]
        chosen = chosen + far_big
        notes.append(Note("within", (("radius", settings.radius_blocks),)))
        if far_big:
            # The console is where "why is this row here when my radius is 6?" is answered.
            notes.append(Note("big_far",
                              (("count", len(far_big)),
                               ("radius", settings.radius_blocks))))

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
        # "N nearby" counts the rows the radius accounts for, not the big bosses that were
        # let in from outside it: the title must not call something forty blocks away near.
        nearby_sightings=len(chosen) - len(far_big),
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
