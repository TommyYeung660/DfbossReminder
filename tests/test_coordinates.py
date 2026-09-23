"""The coordinate set: parsing, matching, and the two shapes a player uses.

The whitelist that used these is gone - the player replaced it with coordinate styles on
2026-09-23 - but the arithmetic it needed is exactly what a style rule needs, so it moved
here rather than being deleted with the feature.
"""

from __future__ import annotations

import pytest

from dfbossreminder.domain.geometry import Block
from dfbossreminder.domain.coordinates import (
    CoordinateError,
    CoordinateSet,
    covers,
    parse_cell,
    parse_cells,
    to_dict,
)


def test_an_exact_coordinate_matches_only_its_own_block() -> None:
    entry = parse_cell("1055,986")
    assert entry.radius == 0
    assert entry.contains(Block(1055, 986))
    assert not entry.contains(Block(1056, 986))


def test_a_radius_widens_the_entry_to_its_neighbourhood() -> None:
    entry = parse_cell("1055,986:1")
    assert entry.contains(Block(1056, 987))       # a diagonal neighbour is one block
    assert entry.contains(Block(1054, 986))
    assert not entry.contains(Block(1057, 986))   # two blocks east is outside


def test_a_label_is_carried_through_and_shown() -> None:
    entry = parse_cell("1054,987:2=Bunker")
    assert entry.label == "Bunker"
    assert entry.describe() == "1054,987:2 (Bunker)"


def test_entries_may_be_separated_by_semicolons_or_newlines() -> None:
    entries = parse_cells("1055,986; 1057,1017\n1054,987:1")
    assert [str(entry.block) for entry in entries] == ["1055,986", "1057,1017", "1054,987"]


def test_a_list_of_dicts_is_the_same_thing_as_the_text_form() -> None:
    from_json = parse_cells([{"x": 1055, "y": 986, "radius": 1, "label": "spot"}])
    from_text = parse_cells("1055,986:1=spot")
    assert from_json == from_text


def test_the_set_round_trips_through_its_json_form() -> None:
    entries = parse_cells("1055,986:1=spot;1054,987")
    assert parse_cells(to_dict(entries)) == entries


def test_a_typo_is_reported_rather_than_silently_never_matching() -> None:
    for bad in ("1055", "1055,986,1", "x,y", "1055,986:-1", "1055,986:two", ""):
        with pytest.raises(CoordinateError):
            parse_cell(bad)


def test_a_dict_without_a_coordinate_is_rejected() -> None:
    with pytest.raises(CoordinateError):
        parse_cells([{"x": 1055}])


def test_a_set_covers_a_block_when_any_of_its_cells_does() -> None:
    cells = parse_cells("1055,986:1")
    assert covers(cells, Block(1056, 986))
    assert not covers(cells, Block(1000, 1000))


def test_an_empty_set_covers_nothing() -> None:
    assert not covers((), Block(1, 1))
    assert parse_cells(None) == ()
    assert parse_cells("") == ()


def test_an_entry_is_a_value_so_two_entries_compare_by_content() -> None:
    assert parse_cell("1,2") == CoordinateSet(block=Block(1, 2), radius=0, label="")
