"""The readout rows: the exact line the player sees, in the requested format.

The format is the contract with the player, so these tests assert whole lines rather
than "contains a substring": `6 x Bandits | 1052 x 1018 | 5LD1` is either produced
exactly or the readout is wrong.
"""

from __future__ import annotations

import time

from dfbossreminder.domain.bosses import parse_bossmap
from dfbossreminder.domain.geometry import Block
from dfbossreminder.domain.plan import build_plan
from dfbossreminder.domain.settings import parse_settings
from dfbossreminder.ui import view

NOW = 10_000.0


def payload(*specs: dict) -> dict:
    out = {}
    for index, spec in enumerate(specs):
        out[str(index)] = {
            "game_id": str(index),
            "locations": [[str(x), str(y)] for x, y in spec["blocks"]],
            "special_enemy_type": spec["name"],
            "special_enemy_amount": str(spec.get("amount", 1)),
            "start_time": str(NOW - 600),
            "end_time": str(spec.get("end_epoch", NOW + spec.get("minutes_left", 60) * 60)),
        }
    return out


def plan_for(specs: list[dict], player: Block | None, **settings) -> object:
    events = parse_bossmap(payload(*specs), NOW)
    return build_plan(events, player, parse_settings(settings), NOW)


def test_a_normal_boss_line_is_exactly_the_requested_format() -> None:
    # The example from the requirement, checked field by field: name, absolute block,
    # and the compact bearing that 1057,1017 -> 1052,1018 produces.
    plan = plan_for([{"name": "6 x Bandits", "blocks": [(1052, 1018)]}], Block(1057, 1017),
                    radius_blocks=10)
    text = view.rows_for(plan, parse_settings({"radius_blocks": 10}))[0].text
    assert text == "6 x Bandits | 1052 x 1018 | 5LD1"


def test_a_big_boss_line_shows_the_end_time_instead_of_a_bearing() -> None:
    # 18:00 is the boss's expiry, in local time, and the count prefix is dropped so
    # the line names the boss rather than a group size of one.
    end = time.mktime((2026, 9, 22, 18, 0, 0, 0, 0, -1))
    plan = plan_for([{"name": "1 x Devil Hound", "blocks": [(1052, 1018)], "end_epoch": end}],
                    Block(1057, 1017), radius_blocks=10)
    text = view.rows_for(plan, parse_settings({"radius_blocks": 10}))[0].text
    assert text == "Devil Hound | 1052 x 1018 | 18:00"


def test_the_tier_comes_from_the_configured_name_list() -> None:
    end = time.mktime((2026, 9, 22, 3, 5, 0, 0, 0, -1))
    specs = [{"name": "1 x Volatile Leaper", "blocks": [(1001, 1000)], "end_epoch": end}]
    default = plan_for(specs, Block(1000, 1000), radius_blocks=10)
    assert default.rows[0].is_big
    assert view.rows_for(default, parse_settings({"radius_blocks": 10}))[0].text.endswith("03:05")

    # Configured off, the same boss is drawn as an ordinary one.
    off = parse_settings({"radius_blocks": 10, "big_bosses": []})
    assert not build_plan(parse_bossmap(payload(*specs), NOW), Block(1000, 1000), off, NOW).rows[0].is_big

    # And a boss the player adds becomes big.
    mine = parse_settings({"radius_blocks": 10, "big_bosses": ["Dreadstag"]})
    added = parse_bossmap(payload({"name": "2 x Dreadstag", "blocks": [(1001, 1000)],
                                   "end_epoch": end}), NOW)
    assert build_plan(added, Block(1000, 1000), mine, NOW).rows[0].is_big


def test_a_big_boss_is_listed_before_a_closer_normal_one() -> None:
    # A special spawn is what the player is looking for, so it leads the strip even
    # when an ordinary boss is nearer.
    end = NOW + 3600
    plan = plan_for(
        [{"name": "6 x Bandits", "blocks": [(1001, 1000)]},
         {"name": "1 x Devil Hound", "blocks": [(1005, 1000)], "end_epoch": end}],
        Block(1000, 1000), radius_blocks=10)
    names = [row.name for row in plan.rows]
    assert names == ["1 x Devil Hound", "6 x Bandits"]


def test_the_bearing_is_agnostic_to_the_display_style_setting() -> None:
    # The strip is too narrow for the words, so the compact form is used whatever the
    # console's direction_style says; the setting only changes the console.
    plan = plan_for([{"name": "6 x Bandits", "blocks": [(1052, 1018)]}], Block(1057, 1017),
                    radius_blocks=10, direction_style="zh")
    text = view.rows_for(plan, parse_settings({"radius_blocks": 10}))[0].text
    assert text.endswith("5LD1")


def test_the_colours_come_from_the_theme() -> None:
    plan = plan_for([{"name": "6 x Bandits", "blocks": [(1001, 1000)]}], Block(1000, 1000),
                    radius_blocks=10)
    settings = parse_settings({"radius_blocks": 10})
    assert view.rows_for(plan, settings)[0].colour == (0x33, 0xFF, 0x33)

    custom = parse_settings({"radius_blocks": 10, "colours": {"list": "#FF00FF"}})
    assert view.rows_for(plan, custom)[0].colour == (0xFF, 0x00, 0xFF)


def test_a_big_boss_can_be_given_its_own_colour() -> None:
    end = NOW + 3600
    plan = plan_for([{"name": "1 x Devil Hound", "blocks": [(1001, 1000)], "end_epoch": end}],
                    Block(1000, 1000), radius_blocks=10)
    settings = parse_settings({"radius_blocks": 10, "colours": {"list": "#33FF33",
                                                              "big": "#FFFF00"}})
    assert view.rows_for(plan, settings)[0].colour == (0xFF, 0xFF, 0x00)


def test_the_title_is_trimmed_to_the_configured_width() -> None:
    # The strip under the minimap is narrow, so the longest form that fits is used;
    # the account name is what gives way, because the block and the count are what say
    # the readout is alive and where it thinks the player is.
    plan = plan_for([{"name": "Bandits", "blocks": [(1001, 1000)]}], Block(1000, 1000),
                    radius_blocks=10)
    narrow = parse_settings({"radius_blocks": 10})                    # the shipped width
    title = view.title_line(plan, narrow, "tommy660")
    assert "1000,1000" in title and "1 nearby" in title
    assert view.display_width(title) <= view.columns_for(narrow)

    wide = parse_settings({"radius_blocks": 10, "width": 900})
    assert "tommy660" in view.title_line(plan, wide, "tommy660")


def test_the_title_stays_within_the_width_at_every_shipped_size() -> None:
    plan = plan_for([{"name": "Bandits", "blocks": [(1001, 1000)]}], Block(1000, 1000),
                    radius_blocks=10)
    for width in (220, 260, 300, 340, 430, 900):
        settings = parse_settings({"radius_blocks": 10, "width": width})
        assert view.display_width(view.title_line(plan, settings, "tommy660")) \
            <= view.columns_for(settings)


def test_the_waypoint_uses_the_same_shape_as_a_boss() -> None:
    plan = plan_for([], Block(1057, 1017), radius_blocks=10)
    texts = [row.text for row in view.rows_for(plan, parse_settings({"radius_blocks": 10}))]
    # 3 left, 30 up: the same `{n}L` + `U{n}` shape as a boss's `5LD1`.
    assert "Secronom Bunker | 1054 x 987 | 3LU30" in texts


def test_the_notes_follow_the_rows_in_the_note_colour() -> None:
    plan = plan_for([], Block(1000, 1000), radius_blocks=10)
    settings = parse_settings({"radius_blocks": 10})
    rows = view.rows_for(plan, settings, "updated 1s ago", False)
    assert rows[-1].text == "within 10 blocks"
    assert rows[-1].colour == settings.colour("note")
    assert any(row.text == "updated 1s ago" for row in rows)


def test_a_long_boss_name_is_elided_rather_than_overflowing() -> None:
    plan = plan_for([{"name": "x" * 80, "blocks": [(1001, 1000)]}], Block(1000, 1000),
                    radius_blocks=10)
    text = view.rows_for(plan, parse_settings({"radius_blocks": 10}))[0].text
    assert "…" in text
    assert text.endswith("| 1001 x 1000 | 1R")


def test_a_name_that_would_overflow_gives_way_to_the_coordinate_and_bearing() -> None:
    # The live failure: a joined multi-boss name is long enough that a fixed name
    # budget pushed the line past the panel, and the window's own ellipsis then ate the
    # block and the bearing. Every field must survive, so the name is what is trimmed.
    plan = plan_for([{"name": "1 x Evolved Longarms + 1 x Irradiated Evolved Longarms",
                      "blocks": [(1048, 1018)]}], Block(1057, 1017), radius_blocks=20)
    settings = parse_settings({"radius_blocks": 20})
    text = view.rows_for(plan, settings)[0].text
    assert text.endswith("| 1048 x 1018 | 9LD1")
    assert view.display_width(text) <= view.columns_for(settings)


def test_every_shipped_row_fits_the_shipped_width() -> None:
    # A guard for the whole strip: at the default size, no row may be wider than the
    # panel, because the panel's ellipsis would silently drop whatever is last.
    end = time.mktime((2026, 9, 22, 18, 0, 0, 0, 0, -1))
    specs = [{"name": "6 x Bandits", "blocks": [(1002, 1017)]},
             {"name": "1 x Charred Titan", "blocks": [(1048, 1018)]},
             {"name": "1 x Devil Hound", "blocks": [(1052, 1018)], "end_epoch": end},
             {"name": "1 x Evolved Longarms + 1 x Irradiated Evolved Longarms",
              "blocks": [(1047, 1012)]}]
    settings = parse_settings({})
    plan = plan_for(specs, Block(1057, 1017), radius_blocks=40,
                    big_bosses=["Devil Hound"])
    for row in view.rows_for(plan, settings):
        assert view.display_width(row.text) <= view.columns_for(settings), row.text


def test_a_wide_character_counts_as_two_columns_when_eliding() -> None:
    assert view.display_width("abc") == 3
    assert view.display_width("3右2上") == 6
    plan = plan_for([{"name": "中" * 40, "blocks": [(1001, 1000)]}], Block(1000, 1000),
                    radius_blocks=10)
    text = view.rows_for(plan, parse_settings({"radius_blocks": 10}))[0].text
    assert view.display_width(text.split(" | ")[0]) <= view.NAME_LIMIT


def test_the_console_form_is_the_same_content_as_plain_text() -> None:
    plan = plan_for([{"name": "6 x Bandits", "blocks": [(1001, 1000)]}], Block(1000, 1000),
                    radius_blocks=10)
    lines = view.console_lines(plan, parse_settings({"radius_blocks": 10}), "updated 0s ago", False)
    assert lines[0].startswith("DFBossReminder")
    assert any("6 x Bandits | 1001 x 1000 | 1R" in line for line in lines)
