"""Settings: per-field fallback, clamping, and the round trip that makes them stick."""

from __future__ import annotations

from dfbossreminder.domain.settings import (
    Settings,
    normalize_user_id,
    parse_settings,
    to_dict,
)
from dfbossreminder.domain.whitelist import parse_whitelist


def test_an_empty_mapping_yields_the_documented_defaults() -> None:
    assert parse_settings({}) == Settings()
    assert parse_settings(None) == Settings()


def test_the_user_id_is_the_one_thing_that_must_be_remembered() -> None:
    settings = parse_settings({"user_id": "14008279"})
    assert settings.user_id == "14008279"
    # The round trip is what makes --user-id persist across runs.
    assert parse_settings(to_dict(settings)).user_id == "14008279"


def test_a_user_id_must_be_digits_of_a_plausible_length() -> None:
    assert normalize_user_id("14008279") == "14008279"
    assert normalize_user_id(14008279) == "14008279"
    assert normalize_user_id(" 14008279 ") == "14008279"
    # A name is not an id, and accepting one would fail later as "unknown user".
    assert normalize_user_id("tommy660") == ""
    assert normalize_user_id("123") == ""
    assert normalize_user_id("1234567890123") == ""
    assert normalize_user_id(None) == ""


def test_one_bad_field_does_not_discard_the_rest() -> None:
    settings = parse_settings({"user_id": "14008279", "radius_blocks": "not a number",
                               "presentation": "hologram"})
    assert settings.user_id == "14008279"
    assert settings.radius_blocks == Settings().radius_blocks
    assert settings.presentation == Settings().presentation


def test_numbers_are_clamped_not_rejected() -> None:
    settings = parse_settings({
        "radius_blocks": 9999, "max_rows": 0, "poll_seconds": 0.1,
        "offset_x": -99999, "stale_seconds": 5,
        "font_size": 99, "opacity": 5, "minimap_size": 10, "minimap_gap": -4,
    })
    assert settings.radius_blocks == 200
    assert settings.max_rows == 1
    assert settings.poll_seconds == 5.0
    assert settings.offset_x == -4000
    assert settings.stale_seconds == 15.0
    assert settings.font_size == 32
    assert settings.opacity == 1.0
    assert settings.minimap_size == 40
    assert settings.minimap_gap == 0


def test_the_radius_is_configurable_as_the_second_requirement_asks() -> None:
    assert parse_settings({"radius_blocks": 25}).radius_blocks == 25
    assert parse_settings({"radius_blocks": "12"}).radius_blocks == 12


def test_the_whitelist_round_trips_and_a_bad_one_only_loses_itself() -> None:
    settings = parse_settings({"user_id": "14008279", "whitelist_mode": True,
                               "whitelist": "1055,986:1=spot"})
    assert settings.whitelist_mode
    assert settings.whitelist == parse_whitelist("1055,986:1=spot")
    assert parse_settings(to_dict(settings)).whitelist == settings.whitelist

    broken = parse_settings({"user_id": "14008279", "whitelist": "nonsense", "radius_blocks": 20})
    assert broken.whitelist == ()
    assert broken.user_id == "14008279"      # the id survives a bad whitelist
    assert broken.radius_blocks == 20


def test_booleans_accept_the_words_a_person_would_type() -> None:
    assert parse_settings({"whitelist_mode": "on"}).whitelist_mode
    assert parse_settings({"whitelist_mode": "true"}).whitelist_mode
    assert not parse_settings({"whitelist_mode": "off"}).whitelist_mode
    assert parse_settings({"include_missions": 1}).include_missions


def test_unknown_keys_are_dropped_rather_than_stored() -> None:
    settings = parse_settings({"user_id": "14008279", "made_up": 3})
    assert settings.user_id == "14008279"
    assert "made_up" not in to_dict(settings)


def test_every_documented_field_survives_the_round_trip_unchanged() -> None:
    settings = parse_settings({
        "user_id": "14012933", "radius_blocks": 30, "whitelist_mode": True,
        "whitelist": [{"x": 1055, "y": 986, "radius": 2, "label": "bunker"}],
        "include_missions": True, "show_all_without_player": False,
        "poll_seconds": 45, "stale_seconds": 300, "presentation": "panel",
        "anchor": "bottom-right", "offset_x": 20, "offset_y": 30, "width": 500,
        "height": 300, "max_rows": 20, "direction_style": "en",
        "font_face": "MS Gothic", "font_size": 15, "opacity": 0.5,
        "colours": {"list": "#00FF00", "big": "#FFFF00", "title": "#00AA00",
                    "note": "#888888", "background": "#000000", "border": "#333333"},
        "minimap_left": 1060, "minimap_top": 10, "minimap_size": 215, "minimap_gap": 6,
        "big_bosses": ["Devil Hound", "Dreadstag"],
        "waypoints": [{"label": "Home", "x": 1054, "y": 987}],
        "watch_pid_seconds": 10,
    })
    assert parse_settings(to_dict(settings)) == settings


def test_a_waypoints_value_of_the_wrong_type_falls_back_to_the_default() -> None:
    defaults = Settings().waypoints
    assert parse_settings({"waypoints": "bunker"}).waypoints == defaults
    assert parse_settings({"waypoints": None}).waypoints == defaults


def test_a_waypoints_list_without_a_usable_entry_means_no_waypoints() -> None:
    # The list itself is the player saying which places they want, so an unusable
    # list is an empty one - not a silent return of the default bunker.
    assert parse_settings({"waypoints": [{"label": "nowhere"}, "junk"]}).waypoints == ()
    assert parse_settings({"waypoints": []}).waypoints == ()


def test_an_empty_base_url_falls_back_to_the_default() -> None:
    assert parse_settings({"base_url": "  "}).base_url == Settings().base_url
    assert parse_settings({"base_url": "https://example.test/"}).base_url == "https://example.test"


def test_a_bad_colour_falls_back_to_the_shipped_one() -> None:
    settings = parse_settings({"colours": {"list": "not a colour", "big": "#0f0"}})
    assert settings.colour("list") == (51, 255, 51)      # the default, not black
    assert settings.colour("big") == (0, 255, 0)
    assert settings.colour("nonexistent") == (255, 255, 255)


def test_a_three_digit_colour_is_expanded() -> None:
    assert parse_settings({"colours": {"list": "#0F0"}}).colour("list") == (0, 255, 0)
    assert parse_settings({"colours": {"list": "0F0"}}).colour("list") == (0, 255, 0)


def test_the_default_theme_is_a_bright_green_list_on_a_dark_backing() -> None:
    settings = Settings()
    assert settings.colour("list") == (0x33, 0xFF, 0x33)
    assert settings.font_size == 12
    assert settings.colour("background")[0] < 40      # dark, so green stays legible


def test_the_default_minimap_rectangle_is_the_measured_one() -> None:
    settings = Settings()
    assert (settings.minimap_left, settings.minimap_top, settings.minimap_size) == (1060, 10, 215)
    assert settings.anchor == "below-minimap"


def test_the_big_boss_list_defaults_to_the_wikis_special_daily_bosses() -> None:
    assert Settings().big_bosses == ("Devil Hound", "Volatile Leaper", "Behemoth")


def test_an_empty_big_boss_list_is_honoured_not_replaced() -> None:
    # Clearing the list is a player saying "I count nothing as big", not a missing value.
    assert parse_settings({"big_bosses": []}).big_bosses == ()
    assert parse_settings({"big_bosses": "Devil Hound"}).big_bosses == Settings().big_bosses
