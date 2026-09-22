"""Screen placement: corners, insets, and the centre, without a screen."""

from __future__ import annotations

from dfbossreminder.ui.layout import ANCHORS, place, place_below_minimap

AREA = (100, 50, 800, 600)      # left, top, width, height


def test_top_left_sits_at_the_corner_plus_the_inset() -> None:
    assert place("top-left", *AREA, 430, 240, 14, 14) == (114, 64)


def test_top_right_measures_from_the_right_edge() -> None:
    left, top = place("top-right", *AREA, 430, 240, 14, 14)
    assert left == 100 + 800 - 430 - 14
    assert top == 64


def test_bottom_left_measures_from_the_bottom_edge() -> None:
    left, top = place("bottom-left", *AREA, 430, 240, 14, 14)
    assert left == 114
    assert top == 50 + 600 - 240 - 14


def test_bottom_right_is_the_far_corner() -> None:
    assert place("bottom-right", *AREA, 430, 240, 14, 14) == (456, 396)


def test_the_centre_centres_the_window() -> None:
    left, top = place("center", *AREA, 430, 240, 0, 0)
    assert left == 100 + (800 - 430) // 2
    assert top == 50 + (600 - 240) // 2


def test_an_unknown_anchor_falls_back_rather_than_crashing() -> None:
    assert place("sideways", *AREA, 430, 240, 0, 0) == place("top-left", *AREA, 430, 240, 0, 0)
    assert place("", *AREA, 430, 240, 0, 0) == place("top-left", *AREA, 430, 240, 0, 0)


def test_a_negative_inset_is_allowed_so_a_window_may_hang_off_the_edge() -> None:
    assert place("top-right", *AREA, 430, 240, -20, 0)[0] == 100 + 800 - 430 + 20


def test_every_anchor_is_placeable() -> None:
    for anchor in ANCHORS:
        left, top = place(anchor, *AREA, 430, 240, 10, 10)
        assert isinstance(left, int) and isinstance(top, int)


def test_below_minimap_hangs_off_the_minimap_and_aligns_to_its_right_edge() -> None:
    # Client at (242,134), minimap at client (1060,10) size 215, readout 300x220:
    # right edges align at 242+1060+215 = 1517, and the top is the minimap's bottom
    # (134+10+215 = 359) plus the gap.
    left, top = place_below_minimap(242, 134, 1060, 10, 215, 300, 220, 4)
    assert left == 1517 - 300
    assert top == 359 + 4


def test_below_minimap_stays_inside_the_client_area() -> None:
    # The measured minimap on a 1280x720 client, with the shipped readout size: the
    # readout must not run past the client's right or bottom edge.
    left, top = place_below_minimap(0, 0, 1060, 10, 215, 300, 220, 4)
    assert left >= 0 and left + 300 <= 1280
    assert top >= 0 and top + 220 <= 720


def test_below_minimap_follows_the_client_when_it_moves() -> None:
    first = place_below_minimap(0, 0, 1060, 10, 215, 300, 220, 4)
    moved = place_below_minimap(300, 200, 1060, 10, 215, 300, 220, 4)
    assert (moved[0] - first[0], moved[1] - first[1]) == (300, 200)


def test_a_wider_readout_shifts_left_rather_than_off_the_minimap() -> None:
    narrow = place_below_minimap(242, 134, 1060, 10, 215, 200, 220, 4)[0]
    wide = place_below_minimap(242, 134, 1060, 10, 215, 400, 220, 4)[0]
    assert wide < narrow
    assert wide == 1517 - 400
