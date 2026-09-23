"""Screen placement: corners, insets, and the centre, without a screen."""

from __future__ import annotations

from dfbossreminder.ui.layout import ANCHORS, nudged, place, place_below_minimap

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


def test_the_offset_nudges_below_minimap_the_same_way_it_nudges_a_corner() -> None:
    # The readout is right-aligned under the minimap, so the nudge has to move it the
    ## same way the arrows say - a feature that only works on some anchors is a feature
    ## the player has to learn twice.
    plain = place_below_minimap(0, 0, 1060, 10, 215, 300, 220, 4)
    moved = place_below_minimap(0, 0, 1060, 10, 215, 300, 220, 4, 10, 10)
    assert moved[0] == plain[0] - 10        # inward from the right edge
    assert moved[1] == plain[1] + 10        # downward from the top


def test_a_wider_readout_shifts_left_rather_than_off_the_minimap() -> None:
    narrow = place_below_minimap(242, 134, 1060, 10, 215, 200, 220, 4)[0]
    wide = place_below_minimap(242, 134, 1060, 10, 215, 400, 220, 4)[0]
    assert wide < narrow
    assert wide == 1517 - 400


# ------------------------------------------------------------- the position nudge


def test_a_nudge_moves_the_window_the_way_the_arrow_points() -> None:
    # The offset is an *inward* inset, so its sign depends on the corner. The arrows in
    # the settings window mean "move the readout right", not "change a number", so the
    # direction is what has to come out the same on every anchor.
    for anchor, corner in (("top-left", (0, 0)), ("top-right", (1000, 0)),
                           ("bottom-left", (0, 500)), ("bottom-right", (1000, 500)),
                           ("center", (500, 250))):
        before = place(anchor, 0, 0, 1280, 720, 340, 220, 0, 0)
        for direction, (dx, dy) in (("right", (5, 0)), ("left", (-5, 0)),
                                    ("down", (0, 5)), ("up", (0, -5))):
            offset_x, offset_y = nudged(anchor, 0, 0, direction, 5)
            after = place(anchor, 0, 0, 1280, 720, 340, 220, offset_x, offset_y)
            assert (after[0] - before[0], after[1] - before[1]) == (dx, dy), \
                f"{anchor} moved wrong for {direction}"


def test_below_minimap_nudges_like_the_corner_it_hangs_from() -> None:
    # Its right edge is the minimap's, so it behaves like top-right - which is also what
    # the OverlayPresenter does with it.
    assert nudged("below-minimap", 0, 0, "right", 5) == nudged("top-right", 0, 0, "right", 5)
    assert nudged("below-minimap", 0, 0, "down", 5) == nudged("top-right", 0, 0, "down", 5)


def test_a_nudge_accumulates_and_an_unknown_direction_does_nothing() -> None:
    offset_x, offset_y = 0, 0
    for _ in range(3):
        offset_x, offset_y = nudged("top-left", offset_x, offset_y, "right", 5)
    assert (offset_x, offset_y) == (15, 0)
    assert nudged("top-left", 10, 10, "sideways", 5) == (10, 10)


def test_a_negative_step_cannot_flip_the_arrow() -> None:
    # A step box the player typed "-5" into must not move the readout the other way.
    assert nudged("top-left", 0, 0, "right", -5) == nudged("top-left", 0, 0, "right", 5)
    assert nudged("top-left", 0, 0, "right", 0) == (0, 0)
