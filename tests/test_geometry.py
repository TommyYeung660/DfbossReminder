"""Block arithmetic: the radius test and the direction words."""

from __future__ import annotations

from dfbossreminder.domain.geometry import Bearing, Block, chebyshev, euclidean


def test_chebyshev_counts_diagonal_steps_as_one() -> None:
    # Eight-way movement, so a diagonal neighbour is one block away, not 1.41.
    assert chebyshev(Block(0, 0), Block(1, 1)) == 1
    assert chebyshev(Block(0, 0), Block(3, 3)) == 3
    assert chebyshev(Block(10, 10), Block(10, 10)) == 0


def test_chebyshev_is_the_larger_axis_gap() -> None:
    assert chebyshev(Block(100, 100), Block(103, 101)) == 3
    assert chebyshev(Block(100, 100), Block(98, 105)) == 5


def test_euclidean_is_only_used_to_order_equals() -> None:
    assert euclidean(Block(0, 0), Block(3, 4)) == 5.0


def test_bearing_names_the_axes_the_way_the_player_reads_them() -> None:
    bearing = Bearing.between(Block(1057, 1017), Block(1060, 1015))
    assert bearing.blocks == 3
    assert bearing.horizontal == "E"
    assert bearing.vertical == "N"
    assert bearing.describe("zh") == "3右2上"
    assert bearing.describe("en") == "E3N2"


def test_bearing_of_the_same_block_says_so() -> None:
    bearing = Bearing.between(Block(5, 5), Block(5, 5))
    assert bearing.blocks == 0
    assert bearing.describe("zh") == "同格"
    assert bearing.describe("en") == "here"


def test_bearing_covers_all_four_quadrants() -> None:
    assert Bearing.between(Block(0, 0), Block(-2, 0)).describe("zh") == "2左"
    assert Bearing.between(Block(0, 0), Block(0, -4)).describe("zh") == "4上"
    assert Bearing.between(Block(0, 0), Block(0, 4)).describe("zh") == "4下"
    assert Bearing.between(Block(0, 0), Block(7, 0)).describe("zh") == "7右"


def test_blocks_are_hashable_and_orderable_so_a_set_can_deduplicate_them() -> None:
    assert len({Block(1, 2), Block(1, 2), Block(2, 1)}) == 2
    assert str(Block(1055, 986)) == "1055,986"
