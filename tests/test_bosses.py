"""Boss-map parsing, against the payload the live site actually returned.

The fixture is a trimmed copy of a real ``/bossmap/json/`` response, so these
tests pin the schema the tool depends on rather than a shape invented for the
tests. A change on the site that the parser cannot read must show up here as
"fewer bosses found", not on the player's screen as a wrong coordinate.
"""

from __future__ import annotations

import json
from pathlib import Path

from dfbossreminder.domain.bosses import (
    DAILY_WINDOW_MINUTES,
    TIER_BIG,
    TIER_NORMAL,
    boss_count,
    expand,
    parse_bossmap,
    tier_of,
)
from dfbossreminder.domain.geometry import Block

FIXTURES = Path(__file__).parent / "fixtures"

# The fixture is a real payload with its timestamps shifted to a fixed instant in
# 2033, so the tests do not depend on the wall clock and cannot rot when the boss
# map's own events expire. Every event in it is live at this instant.
BEFORE_THE_FIXTURE = 2_000_000_000.0


def load() -> dict:
    return json.loads((FIXTURES / "bossmap.json").read_text(encoding="utf-8"))


def test_the_fixture_is_the_shape_the_parser_expects() -> None:
    payload = load()
    assert payload and all(isinstance(value, dict) for value in payload.values())
    assert any(entry.get("special_enemy_type") for entry in payload.values())


def test_only_live_boss_events_with_locations_are_returned() -> None:
    events = parse_bossmap(load(), BEFORE_THE_FIXTURE)
    assert events
    for event in events:
        assert event.name and event.name != "0"
        assert event.blocks
        assert event.end > BEFORE_THE_FIXTURE
        assert not event.is_mission      # missions are excluded by default


def test_missions_are_included_only_when_asked_for() -> None:
    with_missions = parse_bossmap(load(), BEFORE_THE_FIXTURE, include_missions=True)
    without = parse_bossmap(load(), BEFORE_THE_FIXTURE)
    assert len(with_missions) > len(without)
    assert all(event.is_mission for event in with_missions if event.is_mission)
    assert not any(event.is_mission for event in without)


def test_an_expired_event_is_not_returned() -> None:
    payload = load()
    # A time after every end_time in the fixture: the boss map is a snapshot of what
    # is spawned, and an event whose end has passed is not spawned any more.
    after_everything = max(float(entry["end_time"]) for entry in payload.values()) + 60
    assert parse_bossmap(payload, after_everything) == []


def test_a_boss_with_several_spawn_blocks_keeps_them_all_and_deduplicates() -> None:
    payload = {
        "1": {
            "game_id": "1",
            "locations": [["1000", "1000"], ["1001", "1000"], ["1000", "1000"]],
            "special_enemy_type": "2 x Bandits",
            "special_enemy_amount": "2",
            "start_time": "1000",
            "end_time": "9999999999",
        }
    }
    events = parse_bossmap(payload, 5000)
    assert len(events) == 1
    assert events[0].blocks == (Block(1000, 1000), Block(1001, 1000))
    assert events[0].amount == 2
    assert len(expand(events)) == 2


def test_the_numbers_arrive_as_strings_and_are_read_as_numbers() -> None:
    events = parse_bossmap(load(), BEFORE_THE_FIXTURE)
    assert all(isinstance(event.end, float) for event in events)
    assert all(isinstance(block.x, int) and isinstance(block.y, int)
               for event in events for block in event.blocks)


def test_br_tags_become_a_readable_separator_in_the_name() -> None:
    payload = {
        "1": {
            "game_id": "1",
            "locations": [["1000", "1000"]],
            "special_enemy_type": "3 x Irradiated Titan<br />3 x Mega Zombie",
            "start_time": "1",
            "end_time": "9999999999",
        }
    }
    events = parse_bossmap(payload, 5000)
    assert events[0].name == "3 x Irradiated Titan + 3 x Mega Zombie"
    assert "\n" not in events[0].name


def test_a_malformed_entry_is_skipped_rather_than_repaired() -> None:
    payload = {
        "good": {
            "game_id": "9",
            "locations": [["1000", "1000"]],
            "special_enemy_type": "Bandits",
            "start_time": "1",
            "end_time": "9999999999",
        },
        "no_name": {"locations": [["1", "2"]], "end_time": "9999999999"},
        "no_locations": {"special_enemy_type": "Bandits", "end_time": "9999999999"},
        "bad_location": {"locations": [["x", "y"]], "special_enemy_type": "Bandits",
                         "end_time": "9999999999"},
        "not_a_dict": ["nonsense"],
        "no_end": {"locations": [["1", "2"]], "special_enemy_type": "Bandits"},
    }
    events = parse_bossmap(payload, 5000)
    assert len(events) == 1
    assert events[0].name == "Bandits"


def test_a_payload_that_is_not_an_object_yields_nothing() -> None:
    assert parse_bossmap(None, 0) == []
    assert parse_bossmap([1, 2, 3], 0) == []


def test_minutes_left_and_duration_are_computed_from_the_times() -> None:
    payload = {
        "1": {
            "game_id": "1",
            "locations": [["1", "1"]],
            "special_enemy_type": "Bandits",
            "start_time": "1000",
            "end_time": "4600",
        }
    }
    event = parse_bossmap(payload, 1000)[0]
    assert event.duration_minutes == 60.0
    assert event.minutes_left(4000) == 10.0
    assert event.expires_within(4000, 10.0)
    assert not event.expires_within(4000, 5.0)


def test_events_come_back_in_expiry_order() -> None:
    events = parse_bossmap(load(), BEFORE_THE_FIXTURE)
    ends = [event.end for event in events]
    assert ends == sorted(ends)


# ------------------------------------------------------------------ the tier
def event_named(name: str, *, hours: float = 1.0, kind: str = "", include: bool = False):
    """One parsed event, so the tier can be asked about a real payload shape."""
    payload = {
        "1": {
            "game_id": "1",
            "locations": [["1000", "1000"]],
            "special_enemy_type": name,
            "start_time": "0",
            "end_time": str(hours * 3600),
            "event_type": kind,
        }
    }
    return parse_bossmap(payload, 0, include_missions=include)[0]


def test_the_boss_count_is_read_from_the_name_the_map_publishes() -> None:
    # Every field the tier needs is in the name: the map carries one count per boss and joins
    # several bosses with <br />, which the parser turns into " + ".
    assert boss_count("1 x Devil Hound") == 1
    assert boss_count("4 x Flaming Zombie") == 4
    assert boss_count("1 x Flaming Zombie + 2 x Riot Shield Guy") == 3
    assert boss_count("Menace") == 1, "a name with no count is one boss"


def test_a_single_boss_on_a_long_window_is_a_special_boss() -> None:
    # The daily: one boss, three hours, one block.
    assert tier_of(event_named("1 x Devil Hound", hours=3)) == TIER_BIG
    # And the two-hour case the player mentioned: some special dailies last two hours, and a
    # single boss on one is still special.
    assert tier_of(event_named("1 x Snow Dreadstag", hours=2)) == TIER_BIG


def test_a_two_hour_boss_group_is_not_a_special_boss() -> None:
    # The player, 2026-10-07: "2小時的 boss 群不應該當是ultra boss, 也要受半徑限制". Seven of
    # the eight two-hour entries in the live feed spawn several different bosses in one event,
    # and one spawns four of the same; a Special Daily is a single boss.
    assert tier_of(event_named("1 x Flaming Zombie + 2 x Riot Shield Guy", hours=2)) == TIER_NORMAL
    assert tier_of(event_named("2 x Charred Mother + 1 x Charred Wraith", hours=2)) == TIER_NORMAL
    assert tier_of(event_named("4 x Flaming Zombie", hours=2)) == TIER_NORMAL, (
        "four of the same boss is still a group, not a daily")


def test_a_city_cycle_is_not_a_special_boss_however_it_is_named() -> None:
    # One hour is the ordinary cycle, and the count does not make it special either.
    assert tier_of(event_named("1 x Devil Hound", hours=1)) == TIER_NORMAL
    assert tier_of(event_named("6 x Bandits", hours=1)) == TIER_NORMAL
    assert tier_of(event_named("1 x Devil Hound", hours=DAILY_WINDOW_MINUTES / 60)) == TIER_NORMAL


def test_a_mission_is_never_a_special_boss() -> None:
    # Eleven-hour windows belong to missions, which are not bosses at all.
    mission = event_named("700 x 59", hours=11.58, kind="mission", include=True)
    assert mission.is_mission
    assert tier_of(mission) == TIER_NORMAL
