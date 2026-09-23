"""Coordinate styles: the rule the player writes, and the colour a row gets.

The request was concrete - "1015,999 and 1020,998, when there is a boss, show it in red"
- so the tests are too: that exact rule, in the exact words the player used, and what it
does and does not do to a row.
"""

from __future__ import annotations

import pytest

from dfbossreminder.domain.colours import hex_to_rgb, normalize_colour
from dfbossreminder.domain.geometry import Block
from dfbossreminder.domain.styles import (
    StyleError,
    colour_for,
    parse_highlight,
    parse_highlights,
    to_dict,
)


def test_the_players_own_request_parses() -> None:
    # "1015,999 and 1020,998, when there is a boss, show it in red" - as typed.
    highlight = parse_highlight("red=1015,999;1020,998")
    assert highlight.colour == "#FF3333"
    assert highlight.matches(Block(1015, 999))
    assert highlight.matches(Block(1020, 998))
    assert not highlight.matches(Block(1015, 1000))


def test_a_colour_may_be_a_name_or_a_hex_code() -> None:
    assert parse_highlight("red=1,2").colour == "#FF3333"
    assert parse_highlight("RED=1,2").colour == "#FF3333"
    assert parse_highlight("#ff3333=1,2").colour == "#FF3333"
    assert parse_highlight("ff3333=1,2").colour == "#FF3333"


def test_a_colour_that_is_neither_is_refused_rather_than_drawn_white() -> None:
    # Silently drawing the default colour would look like the rule works.
    for bad in ("chartreuse=1,2", "=1,2", "#12345=1,2", "#GGGGGG=1,2"):
        with pytest.raises(StyleError):
            parse_highlight(bad)


def test_a_rule_needs_a_coordinate() -> None:
    for bad in ("red", "red=", "red=;", "red=nonsense"):
        with pytest.raises(StyleError):
            parse_highlight(bad)


def test_a_radius_widens_the_rule_to_the_neighbourhood() -> None:
    highlight = parse_highlight("red=1055,986:1")
    assert highlight.matches(Block(1056, 987))     # a diagonal neighbour is one block
    assert not highlight.matches(Block(1057, 986))


def test_the_rules_json_form_round_trips() -> None:
    rules = parse_highlights([{"colour": "red", "cells": "1015,999;1020,998"},
                              {"colour": "#00FF00", "cells": [{"x": 1057, "y": 1017,
                                                               "radius": 2}]}])
    assert parse_highlights(to_dict(rules)) == rules
    # The cells go out as parsed data, not as their display text: a cell with a label
    # describes itself as "1055,986 (home)", which the parser would not take back.
    assert to_dict(rules)[0]["cells"] == [
        {"x": 1015, "y": 999, "radius": 0, "label": ""},
        {"x": 1020, "y": 998, "radius": 0, "label": ""},
    ]


def test_a_list_of_rules_parses_from_text_or_mappings() -> None:
    assert len(parse_highlights("red=1,2|green=3,4")) == 2
    assert len(parse_highlights([{"colour": "red", "cells": "1,2"}])) == 1
    assert parse_highlights(None) == ()
    assert parse_highlights([]) == ()


def test_the_first_matching_rule_wins() -> None:
    # Order is the player's, and it is visible in the window, so it decides - rather
    # than a precedence rule that nobody can see while editing.
    rules = parse_highlights("red=1015,999|green=1015,999")
    assert colour_for(rules, Block(1015, 999)) == "#FF3333"
    assert colour_for(rules, Block(1, 1)) is None


def test_a_bad_rule_in_a_list_is_reported_not_skipped() -> None:
    with pytest.raises(StyleError):
        parse_highlights([{"colour": "red", "cells": "1,2"}, {"colour": "", "cells": "3,4"}])
    with pytest.raises(StyleError):
        parse_highlights([{"colour": "red", "cells": ""}])


def test_colour_helpers_are_the_single_place_that_parses_colours() -> None:
    assert hex_to_rgb("red") == (255, 255, 255)          # names are for rules, not here
    assert hex_to_rgb("#33FF33") == (0x33, 0xFF, 0x33)
    assert normalize_colour("red") == "#FF3333"
    assert normalize_colour("#abcdef") == "#ABCDEF"
    assert normalize_colour("nonsense") is None
