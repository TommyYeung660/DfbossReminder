"""Screen placement, as arithmetic that can be tested without a screen.

The overlay is anchored to either the game's client rectangle (the in-game mode the
player asked for) or the whole screen (the panel mode, which stays outside the
game on purpose). Both are rectangles, so one function places the window in both
cases, and it is pure - which is why "top-right means the right edge minus the
width" has a test rather than a screenshot.
"""

from __future__ import annotations

# Anchors are corners; ``center`` is offered because a small boss readout is least
# intrusive in the middle-top of a client area, where the game draws no HUD.
ANCHORS = ("below-minimap", "top-left", "top-right", "bottom-left", "bottom-right", "center")

# The four directions a position nudge can go, as the arrows in the settings window.
NUDGE_DIRECTIONS = ("left", "right", "up", "down")


def nudged(
    anchor: str,
    offset_x: int,
    offset_y: int,
    direction: str,
    step: int = 5,
) -> tuple[int, int]:
    """The offsets that move the window one step in this direction.

    ``offset_x/offset_y`` are measured *inward* from the anchored corner, so which way
    an offset moves the window depends on which corner that is: on a left anchor a
    bigger x pushes right, on a right anchor it pulls left. The arrows in the settings
    window have to mean "move the readout right", not "change a number", so the sign is
    worked out here rather than left for the player to discover.

    ``below-minimap`` is right-aligned - its right edge is the minimap's - so it behaves
    like ``top-right``, which is also what ``_corner`` does with it.
    """
    name = (anchor or "top-left").strip().lower()
    if name == "below-minimap":
        name = "top-right"
    if name not in ANCHORS:
        name = "top-left"
    step = abs(int(step))
    dx = step if direction == "right" else -step if direction == "left" else 0
    dy = step if direction == "down" else -step if direction == "up" else 0
    sign_x = -1 if name.endswith("right") else 1
    sign_y = -1 if name.startswith("bottom") else 1
    return int(offset_x + dx * sign_x), int(offset_y + dy * sign_y)


def place_below_minimap(
    client_left: int,
    client_top: int,
    minimap_left: int,
    minimap_top: int,
    minimap_size: int,
    width: int,
    height: int,
    gap: int = 4,
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[int, int]:
    """The readout's corner, hanging under the region minimap inside the client area.

    ``minimap_left/top`` and the client origin are both in client coordinates, so the
    readout's right edge is aligned with the minimap's right edge: the corner the
    player's eye is already at, and the arrangement that leaves the least gameplay
    covered. The numbers were measured off a live 1280x720 client capture rather than
    assumed - the minimap's own ``BUNKER`` header and ``1057 X 1017`` readout both sit
    inside the measured rectangle.

    ``offset_x/offset_y`` are applied on top, inward from the right edge and downward
    from the top, so the position nudge in the settings window works here the same way
    it does for the corner anchors.
    """
    right_edge = client_left + minimap_left + minimap_size
    return (int(right_edge - width - offset_x),
            int(client_top + minimap_top + minimap_size + gap + offset_y))


def place(
    anchor: str,
    area_left: int,
    area_top: int,
    area_width: int,
    area_height: int,
    width: int,
    height: int,
    offset_x: int = 0,
    offset_y: int = 0,
) -> tuple[int, int]:
    """Top-left corner for a ``width x height`` window inside a rectangle.

    The offset pushes the window *inward* from its corner, so a positive offset is
    always "further from the edge" regardless of which corner was chosen; a
    negative one is allowed, because a player may deliberately want the overlay to
    hang off the client area.
    """
    anchor = (anchor or "top-left").strip().lower()
    if anchor not in ANCHORS:
        anchor = "top-left"
    if anchor.startswith("top"):
        top = area_top + offset_y
    elif anchor.startswith("bottom"):
        top = area_top + area_height - height - offset_y
    else:
        top = area_top + (area_height - height) // 2 + offset_y
    if anchor.endswith("left"):
        left = area_left + offset_x
    elif anchor.endswith("right"):
        left = area_left + area_width - width - offset_x
    else:
        left = area_left + (area_width - width) // 2 + offset_x
    return int(left), int(top)
