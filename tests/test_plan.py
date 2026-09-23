"""The plan: the whitelist first, then the radius, then nearest-first.

These are the three things the player asked for, as rules that can be checked with
no game running: a configurable radius around the player's live block, a whitelist
mode, and the nearest boss named first.
"""

from __future__ import annotations

from dfbossreminder.domain.bosses import parse_bossmap
from dfbossreminder.domain.geometry import Block
from dfbossreminder.domain.plan import Note, build_plan, waypoint_rows
from dfbossreminder.domain.settings import parse_settings

NOW = 10_000.0


def payload(*events: dict) -> dict:
    """A boss-map payload from ``(name, blocks, end)`` triples."""
    out = {}
    for index, event in enumerate(events):
        locations = event.get("blocks", [(1000, 1000)])
        out[str(index)] = {
            "game_id": str(index),
            "locations": [[str(x), str(y)] for x, y in locations],
            "special_enemy_type": event.get("name", "Bandits"),
            "special_enemy_amount": str(event.get("amount", 1)),
            "boss_num": str(event.get("boss_num", 1)),
            "event_type": "mission" if event.get("mission") else "",
            "start_time": str(NOW - 600),
            "end_time": str(NOW + event.get("minutes_left", 60) * 60),
        }
    return out


def events(*specs: dict) -> list:
    return parse_bossmap(payload(*specs), NOW)


def test_only_bosses_within_the_radius_are_shown() -> None:
    player = Block(1000, 1000)
    found = events(
        {"name": "Near", "blocks": [(1002, 1002)]},     # 2 blocks
        {"name": "Edge", "blocks": [(1005, 1000)]},     # 5 blocks
        {"name": "Far", "blocks": [(1009, 1000)]},      # 9 blocks
    )
    plan = build_plan(found, player, parse_settings({"radius_blocks": 5}), NOW)
    names = [row.name for row in plan.rows]
    assert names == ["Near", "Edge"]
    assert plan.beyond_radius == 1
    assert Note("within", (("radius", 5),)) in plan.notes


def test_the_radius_is_dynamic_because_it_is_a_setting() -> None:
    player = Block(1000, 1000)
    found = events({"name": "Far", "blocks": [(1009, 1000)]})
    assert build_plan(found, player, parse_settings({"radius_blocks": 3}), NOW).rows == ()
    assert build_plan(found, player, parse_settings({"radius_blocks": 20}), NOW).rows


def test_the_nearest_boss_comes_first() -> None:
    player = Block(1000, 1000)
    found = events(
        {"name": "Far", "blocks": [(1008, 1000)]},
        {"name": "Near", "blocks": [(1001, 1000)]},
        {"name": "Middle", "blocks": [(1004, 1000)]},
    )
    plan = build_plan(found, player, parse_settings({"radius_blocks": 20}), NOW)
    assert [row.name for row in plan.rows] == ["Near", "Middle", "Far"]
    assert [row.distance for row in plan.rows] == [1, 4, 8]


def test_a_bearing_is_given_for_each_boss() -> None:
    player = Block(1000, 1000)
    plan = build_plan(events({"name": "East", "blocks": [(1003, 998)]}), player,
                      parse_settings({"radius_blocks": 20}), NOW)
    assert plan.rows[0].direction("zh") == "3右2上"
    assert plan.rows[0].direction("en") == "E3N2"


def test_a_style_rule_never_removes_a_row() -> None:
    # This is the whole difference from the whitelist it replaced: a rule changes how a
    # matching row is drawn and nothing else, so a style for one corner of the map does
    # not hide the rest of it.
    player = Block(1000, 1000)
    found = events(
        {"name": "Styled", "blocks": [(1001, 1000)]},
        {"name": "Plain", "blocks": [(1002, 1000)]},
        {"name": "Far", "blocks": [(1200, 1200)]},
    )
    settings = parse_settings({"radius_blocks": 20, "highlights": "red=1001,1000"})
    plan = build_plan(found, player, settings, NOW)
    assert [row.name for row in plan.rows] == ["Styled", "Plain"]
    assert settings.style_colour(Block(1001, 1000)) == (0xFF, 0x33, 0x33)
    assert settings.style_colour(Block(1002, 1000)) is None


def test_the_plan_says_how_many_rules_are_loaded_and_how_many_rows_matched() -> None:
    # "Why is it not red?" is answered by seeing that the rule is loaded and that no boss
    # is standing on it, rather than by guessing at the settings file.
    player = Block(1000, 1000)
    found = events({"name": "Plain", "blocks": [(1002, 1000)]})
    hit = build_plan(found, player,
                     parse_settings({"radius_blocks": 20, "highlights": "red=1002,1000"}), NOW)
    assert Note("styles", (("rules", 1), ("matched", 1))) in hit.notes
    miss = build_plan(found, player,
                      parse_settings({"radius_blocks": 20, "highlights": "red=1001,1000"}), NOW)
    assert Note("styles", (("rules", 1), ("matched", 0))) in miss.notes
    # No rules at all means no note: the default readout should not carry a line about a
    # feature nobody is using.
    assert not [note for note in build_plan(found, player, parse_settings({}), NOW).notes
                if note.code == "styles"]


def test_a_rule_with_a_radius_styles_the_whole_neighbourhood() -> None:
    player = Block(1000, 1000)
    found = events({"name": "Near", "blocks": [(1001, 1001)]})
    settings = parse_settings({"radius_blocks": 20, "highlights": "red=1000,1000:1"})
    plan = build_plan(found, player, settings, NOW)
    assert len(plan.rows) == 1
    assert settings.style_colour(plan.rows[0].block) == (0xFF, 0x33, 0x33)


def test_with_no_player_position_everything_is_listed_with_a_note() -> None:
    found = events({"name": "A", "blocks": [(1001, 1000)]})
    plan = build_plan(found, None, parse_settings({"radius_blocks": 3}), NOW)
    assert [row.name for row in plan.rows] == ["A"]
    assert plan.rows[0].distance is None
    assert plan.rows[0].direction("en") == "?"
    assert Note("no_player") in plan.notes


def test_with_no_player_position_the_plan_can_be_told_to_show_nothing() -> None:
    found = events({"name": "A", "blocks": [(1001, 1000)]})
    settings = parse_settings({"show_all_without_player": False})
    plan = build_plan(found, None, settings, NOW)
    assert plan.rows == ()
    assert Note("no_player") in plan.notes


def test_a_very_close_boss_is_marked() -> None:
    player = Block(1000, 1000)
    found = events({"name": "Here", "blocks": [(1001, 1000)]}, {"name": "Away", "blocks": [(1006, 1000)]})
    plan = build_plan(found, player, parse_settings({"radius_blocks": 20, "emphasis_blocks": 1}), NOW)
    here = next(row for row in plan.rows if row.name == "Here")
    away = next(row for row in plan.rows if row.name == "Away")
    assert here.distance == 1
    assert away.distance == 6


def test_a_row_carries_its_expiry_for_the_end_time_readout() -> None:
    player = Block(1000, 1000)
    found = events({"name": "1 x Devil Hound", "blocks": [(1001, 1000)], "minutes_left": 120})
    plan = build_plan(found, player, parse_settings({"radius_blocks": 20}), NOW)
    row = plan.rows[0]
    assert row.end_epoch == NOW + 7200
    assert row.is_big                                    # from the default tier list
    assert row.short_name == "Devil Hound"


def test_the_row_cap_is_reported_rather_than_silent() -> None:
    player = Block(1000, 1000)
    found = events(*[{"name": f"B{i}", "blocks": [(1001 + i, 1000)]} for i in range(6)])
    plan = build_plan(found, player, parse_settings({"radius_blocks": 20, "max_rows": 2}), NOW)
    assert len(plan.rows) == 2
    assert plan.shown == 2
    assert plan.nearby_sightings == 6
    assert Note("capped", (("count", 4),)) in plan.notes


def test_one_event_with_many_blocks_becomes_one_row_per_nearby_block() -> None:
    player = Block(1000, 1000)
    found = events({"name": "Cycle", "blocks": [(1001, 1000), (1002, 1000), (1500, 1500)]})
    plan = build_plan(found, player, parse_settings({"radius_blocks": 5}), NOW)
    assert len(plan.rows) == 2
    assert plan.total_sightings == 3


def test_missions_are_only_present_when_the_setting_asked_for_them() -> None:
    # Parsing honours include_missions too, so both halves of the setting are used:
    # the event only exists when it is asked for, and the plan only lists it then.
    raw = payload({"name": "Mission", "blocks": [(1001, 1000)], "mission": True})
    assert parse_bossmap(raw, NOW) == []
    found = parse_bossmap(raw, NOW, include_missions=True)
    assert build_plan(found, Block(1000, 1000), parse_settings({"include_missions": True}), NOW).rows
    plan = build_plan(found, Block(1000, 1000),
                      parse_settings({"include_missions": True, "radius_blocks": 8}), NOW)
    assert plan.rows[0].is_mission
    assert Note("missions") in plan.notes


def test_the_waypoint_bearing_is_always_available() -> None:
    settings = parse_settings({})
    rows = waypoint_rows(settings, Block(1057, 1017))
    assert rows == [("Secronom Bunker", "3左30上")]
    assert waypoint_rows(settings, None) == []
