"""The box column: the tick boxes, the rule for what a tick hides, and the pump.

Three things the player asked for, and the tests are grouped the way they were asked:

1. a box on every boss row;
2. a left click on one hides that boss's *related* rows - every row of the same spawn,
   because a boss is one event at several blocks;
3. and it does **not** affect the next cycle's readout.

Nothing here needs Windows. The geometry is pure arithmetic by design: what makes a click
land on a box is a comparison of two numbers, so it can be tested on the development
machine, and the probe on the game PC only has to confirm that the real window agrees.
"""

from __future__ import annotations

from dfbossreminder.domain.bosses import parse_bossmap
from dfbossreminder.domain.dismissed import Dismissed
from dfbossreminder.domain.plan import build_plan
from dfbossreminder.domain.settings import parse_settings
from dfbossreminder.ui import panel, view

PLAYER = None          # a plan with no position lists everything, which is enough here


def bossmap(*entries) -> dict:  # noqa: ANN001
    """A boss-map payload from ``(game_id, name, start, [blocks])`` tuples."""
    payload = {}
    for index, (game_id, name, start, blocks) in enumerate(entries):
        payload[str(index)] = {
            "game_id": str(game_id),
            "special_enemy_type": name,
            "special_enemy_amount": "1",
            "boss_num": "1",
            "event_type": "",
            "start_time": str(start),
            "end_time": str(start + 3600),
            "locations": [[str(x), str(y)] for x, y in blocks],
        }
    return payload


# ------------------------------------------------------- the player's field notes
def test_the_field_note_tables_are_well_formed() -> None:
    # The tables are generated from two screenshots by tools/build-fieldnotes.py and checked
    # against the live boss map (every `6 x Bandits` spawn block the game reports is in the
    # bandit table). These tests pin the shape of what that script produces, so a bad rerun
    # cannot pass unnoticed.
    from dfbossreminder.domain import fieldnotes

    assert len(fieldnotes.BANDIT_SPAWNS) == 30, "one dot per area block on the player's map"
    assert fieldnotes.WALLS, "the fighting map has wall notes"
    for code in fieldnotes.BANDIT_SPAWNS.values():
        assert code in {"C", "L", "R", "LU", "LD", "CU", "CD", "RU", "RD"}, code
    for code in fieldnotes.WALLS.values():
        assert code.startswith("W")
        assert code[1:] in {"C", "L", "R", "LU", "LD", "CU", "CD", "RU", "RD"}, code
    # The wall map covers blocks inside the bandit map's area: the same stretch of Death Row.
    bandit_x = {block[0] for block in fieldnotes.BANDIT_SPAWNS}
    wall_x = {block[0] for block in fieldnotes.WALLS}
    assert wall_x <= bandit_x, "the fighting map is the same area"


def test_a_block_with_a_bandit_note_and_a_wall_note_answers_by_row() -> None:
    from dfbossreminder.domain import fieldnotes

    shared = sorted(set(fieldnotes.BANDIT_SPAWNS) & set(fieldnotes.WALLS))
    assert shared, "the two maps overlap, which is why one note has to win"
    block = shared[0]

    class Where:
        x, y = block

    assert fieldnotes.remark_for(Where(), bandits=True) == fieldnotes.BANDIT_SPAWNS[block]
    assert fieldnotes.remark_for(Where(), bandits=False) == fieldnotes.WALLS[block]
    assert fieldnotes.remark_for(Where(), bandits=False).startswith("W")


# ------------------------------------------------------------------ the boxes
def test_a_box_is_the_size_of_the_font_and_the_column_follows_it() -> None:
    # The box belongs to the row it sits next to, so it is sized from the same setting the
    # line height is: a fixed size would look bolted on at 18 px and float at 8 px.
    assert panel.check_size(10) == 10
    assert panel.check_size(4) == 8                  # never smaller than a click target
    assert panel.check_size(40) == 16                # and never a slab either
    assert panel.check_column_width(10) == 10 + 2 * panel.CHECK_PAD
    assert panel.check_gutter(10) == panel.check_column_width(10) + panel.CHECK_TEXT_GAP


def test_the_readout_gives_up_room_for_the_boxes() -> None:
    # Without the gutter the text draws straight under the boxes: the row is elided by the
    # drawing rectangle, which eats the block coordinate and the bearing first - the two
    # fields the row exists for.
    settings = parse_settings({"font_size": 12, "width": 340})
    full = view.columns_for(settings)
    narrower = view.columns_for(settings, gutter=panel.check_gutter(12))
    assert narrower < full
    assert full - narrower >= 1


def test_there_is_one_box_per_boss_row_and_it_lines_up_with_it() -> None:
    rows = (
        panel.Row("6 x Bandits | 1057 x 1017 | 5L1D", key=("19", 100.0)),
        panel.Row("within 5 blocks", colour=(90, 90, 90)),          # a note: no key
        panel.Row("4 x Bandits | 1056 x 1017 | 5L1D", key=("18", 100.0)),
    )
    boxes = panel.boxes_for(rows, title_band=2, line_height=15, font_size=10)
    assert [box.key for box in boxes] == [("19", 100.0), ("18", 100.0)]
    # The note row keeps its slot: the second box sits two rows down, aligned with the row
    # it belongs to rather than pulled up next to the first.
    first, second = boxes
    offset = (15 - panel.check_size(10)) // 2
    assert first.rect[1] == 2 + 0 * 15 + offset
    assert second.rect[1] == 2 + 2 * 15 + offset
    # Inside the column's own width, and the same width as the window that holds them.
    assert all(box.rect[2] <= panel.check_column_width(10) for box in boxes)


def test_a_row_with_nothing_to_hide_gets_no_box() -> None:
    # Notes, waypoints and the "more not shown" line are not bosses: a box beside them would
    # promise something that does not exist.
    rows = (panel.Row("Secronom Bunker | 1054 x 987 | 3RD2"),)
    assert rows[0].key is None
    assert panel.boxes_for(rows, 2, 15, 10) == ()


def test_the_whole_box_is_clickable_not_just_its_border() -> None:
    # A box drawn as an outline would be a frame with a transparent middle, and a click in
    # the middle would fall through to the game: the drawn fill is what makes the whole box
    # a target, so its alpha must not be zero.
    assert panel.BOX_FILL_ALPHA > 0
    boxes = panel.boxes_for((panel.Row("x", key=("1", 1.0)),), 2, 15, 10)
    box = boxes[0]
    left, top, right, bottom = box.rect
    for point in ((left, top), (right - 1, bottom - 1), ((left + right) // 2, (top + bottom) // 2)):
        assert box.contains(*point), f"{point} is inside the box and must be a target"
    assert not box.contains(left - 1, top)
    assert not box.contains(right, bottom)


def test_a_click_between_two_boxes_is_not_a_click_on_a_box() -> None:
    boxes = panel.boxes_for((panel.Row("a", key=("1", 1.0)),
                             panel.Row("b", key=("2", 1.0))), 2, 15, 10)
    assert panel.box_at(4, boxes[0].rect[1] + 1, boxes) is boxes[0]
    assert panel.box_at(4, boxes[0].rect[3] + 2, boxes) is None      # the gap between rows
    assert panel.box_at(0, boxes[0].rect[1] + 1, boxes) is None      # the column's margin
    assert panel.box_at(999, 999, boxes) is None


def test_the_click_coordinates_are_read_as_signed() -> None:
    # A window dragged to a negative coordinate puts negative values in the message's
    # lparam; read as unsigned, a click on the left edge becomes one 65 000 pixels away.
    assert panel._click_point((20 << 16) | 30) == (30, 20)
    assert panel._click_point((0xFFFF << 16) | 0xFFFF) == (-1, -1)


# ------------------------------------------------------- what a tick hides
def test_a_tick_hides_every_row_of_that_spawn() -> None:
    # The player's example: ``6 X BANDITS | 1057 X 1017`` ticked, and
    # ``6 X BANDITS | 1056 X 1017`` goes too - the live map lists both as locations of one
    # event (game_id 19), so "related" is the spawn, and one box takes all of its rows.
    payload = bossmap((19, "6 x Bandits", 100, [(1057, 1017), (1056, 1017), (1057, 1016)]))
    events = parse_bossmap(payload, now=200)
    settings = parse_settings({"radius_blocks": 200})
    before = build_plan(events, PLAYER, settings, now=200)
    assert len(before.rows) == 3

    dismissed = Dismissed()
    assert dismissed.hide(events[0].cycle_key, events[0].name) is True
    after = build_plan(events, PLAYER, settings, now=200, dismissed=dismissed.keys())
    assert after.rows == ()
    # And the plan says so, in both numbers: one boss, three lines.
    note = next(note for note in after.notes if note.code == "dismissed")
    assert note.values() == {"bosses": 1, "rows": 3}
    assert "下個周期" in view.note_text(note, "zh")


def test_a_different_boss_with_the_same_name_keeps_its_rows() -> None:
    # The live map carries two separate ``2 x Bandits`` events at once, so hiding by name
    # would take out a boss nobody pointed at. The key is the spawn, not the name.
    payload = bossmap((6, "2 x Bandits", 100, [(1013, 1000)]),
                      (7, "2 x Bandits", 100, [(1037, 1018)]))
    events = parse_bossmap(payload, now=200)
    settings = parse_settings({"radius_blocks": 200})
    dismissed = Dismissed()
    dismissed.hide(events[0].cycle_key, "2 x Bandits")
    plan = build_plan(events, PLAYER, settings, now=200, dismissed=dismissed.keys())
    assert [(row.name, row.block.x) for row in plan.rows] == [("2 x Bandits", 1037)]


def test_the_next_cycle_brings_the_boss_back() -> None:
    # Requirement 3, both ways it is guaranteed.
    cycle_one = parse_bossmap(bossmap((19, "6 x Bandits", 100, [(1057, 1017)])), now=200)
    dismissed = Dismissed()
    dismissed.hide(cycle_one[0].cycle_key, "6 x Bandits")

    # (a) the same spawn, still live: still hidden, across as many fetches as happen
    settings = parse_settings({"radius_blocks": 200})
    same = parse_bossmap(bossmap((19, "6 x Bandits", 100, [(1057, 1017)])), now=260)
    assert build_plan(same, PLAYER, settings, 260, dismissed.keys()).rows == ()

    # (b) the next cycle: the same boss, the same place, a new start time - so a new key,
    # and nothing to hide it. No one has to remember to un-dismiss anything.
    cycle_two = parse_bossmap(bossmap((19, "6 x Bandits", 3700, [(1057, 1017)])),
                              now=3800)
    assert cycle_two[0].cycle_key != cycle_one[0].cycle_key
    plan = build_plan(cycle_two, PLAYER, settings, 3800, dismissed.keys())
    assert [row.name for row in plan.rows] == ["6 x Bandits"]


def test_a_dismissal_of_a_spawn_the_feed_dropped_is_forgotten() -> None:
    # The second guarantee, and what keeps a long session's set of keys from growing: a
    # spawn the feed no longer lists is over, so there is nothing left for it to hide.
    dismissed = Dismissed()
    dismissed.hide(("19", 100.0), "6 x Bandits")
    dismissed.hide(("6", 100.0), "2 x Bandits")
    gone = dismissed.keep_only([("19", 100.0), ("7", 100.0)])
    assert gone == ["2 x Bandits"]
    assert len(dismissed) == 1 and ("19", 100.0) in dismissed


def test_ticking_the_same_boss_twice_is_not_a_second_change() -> None:
    # Two clicks on the same boss (a double click, a stale window) must not cost a redraw
    # or a second log line: the loop uses this return value to decide whether to redraw.
    dismissed = Dismissed()
    assert dismissed.hide(("19", 100.0), "6 x Bandits") is True
    assert dismissed.hide(("19", 100.0), "6 x Bandits") is False


def test_a_dismissed_boss_is_not_also_counted_as_beyond_the_radius() -> None:
    # One row, one count. Taking the dismissed rows out before the radius test is what
    # keeps "beyond the radius" meaning "too far away" rather than "not shown for some
    # reason" - the two would otherwise both claim the same boss.
    payload = bossmap((19, "6 x Bandits", 100, [(1057, 1017)]),
                      (20, "Titan", 100, [(1500, 1500)]))
    events = parse_bossmap(payload, now=200)
    settings = parse_settings({"radius_blocks": 5})
    from dfbossreminder.domain.geometry import Block

    dismissed = Dismissed()
    dismissed.hide(events[1].cycle_key, "Titan")           # the far one, hidden by hand
    plan = build_plan(events, Block(1057, 1017), settings, 200, dismissed.keys())
    assert plan.beyond_radius == 0, "the hidden one is not a radius problem"
    assert [row.name for row in plan.rows] == ["6 x Bandits"]


# ------------------------------------------------------------- the wiring
def test_the_rows_the_window_draws_carry_the_spawn_they_belong_to() -> None:
    payload = bossmap((19, "6 x Bandits", 100, [(1057, 1017), (1056, 1017)]))
    events = parse_bossmap(payload, now=200)
    plan = build_plan(events, PLAYER, parse_settings({"radius_blocks": 200}), 200)
    rows = view.rows_for(plan, parse_settings({}), extras=False)
    assert len({row.key for row in rows}) == 1, "both rows are the same spawn"
    assert rows[0].key == events[0].cycle_key
