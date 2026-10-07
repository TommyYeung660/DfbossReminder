"""Read the player's two Death Row maps and write the per-block field notes.

The player sent two annotated screenshots on 2026-10-07 (kept in ``docs/evidence/``):

* **BANDITS SPAWN LOCATIONS** - one round red dot per block, marking where the ``6 x Bandits``
  spawn *inside* that block;
* **DEATH ROW BOSS FIGHTING MAP** - green dots (the player's own positions, ignored) and small
  red bar clusters marking the wall a boss can be trapped against.

Both are read the same way: find the marks, work out which block each one is in, and describe
where in that block it sits as a three-by-three position - ``C``, ``L``, ``R``, plus ``U``/``D``
when it is not on the middle row, with a ``W`` in front for the wall notes.

The block grid is measured, not assumed: the map is stitched from 120 px tiles, and the long
straight seams in both images sit at ``x = 418.5 + 120k`` and ``y = 37.5 + 120k`` (the columns
were measurable directly - four seams at exactly 120 px - and the rows agree with them). The
coordinate anchor is the player's: the bottom-right-most bandit dot is block ``1058,1019``.

Run it to regenerate ``src/dfbossreminder/domain/fieldnotes.py``; ``--draw`` writes the
verification image that shows every code drawn on the map it came from, which is how the
reading was checked by eye.

Usage (any machine with Pillow):
    python3 tools/build-fieldnotes.py --draw /tmp/fieldnotes-check.png
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = PROJECT_ROOT / "docs" / "evidence"
SPAWN_MAP = EVIDENCE / "2026-10-07-deathrow-bandits.png"
FIGHT_MAP = EVIDENCE / "2026-10-07-deathrow-fighting.png"
TARGET = PROJECT_ROOT / "src" / "dfbossreminder" / "domain" / "fieldnotes.py"

# The block grid, measured from each map's own seams. The two screenshots are cropped
# differently - the fighting map sits 37 px right and 6 px down from the spawn map - so each
# one carries its own phase. Both are 120 px tiles, measured on four seams apiece.
GRID_SPAWN = (418.5, 37.5)
GRID_FIGHT = (455.5, 44.0)
CELL = 120.0
GRID_X, GRID_Y = GRID_SPAWN          # the anchor image
# The anchor the player gave: the bottom-right-most bandit dot is this block.
ANCHOR_BLOCK = (1058, 1019)
# The annotations are pure red; the map's own scenery is desaturated by comparison, which is
# what makes a tight match on this colour work where a loose one picked up buildings.
ANNOTATION_RGB = (255, 2, 0)
COLOUR_TOLERANCE = 60
# The images' own furniture, which is drawn in the same red as the marks and has to be kept
# out by hand: the fighting map's title band, its legend box, and the "Not Death Row / Death
# Row" label strip above the main body of the map. Everything else is found by colour.
EXCLUDE = {
    "fight": [(0, 0, 790, 118),         # title (the north arm's tiles start to its right)
              (55, 125, 615, 345),      # legend box (the red sample circle and its text)
              (0, 345, 790, 408)],      # the two region labels, left of the north arm
    "spawn": [],
}


def on_the_map(image: np.ndarray, x: float, y: float, radius: int = 22,
               floor: float = 0.35) -> bool:
    """Whether a mark sits on map art rather than on the black background.

    Both maps are annotated with the region's name in the same red as the marks ("Not Death
    Row", "Boss Aggro (trapped)"), and those labels sit on black. A mark surrounded by black is
    a label, not a wall.
    """
    height, width = image.shape[:2]
    x0, x1 = max(0, int(x) - radius), min(width, int(x) + radius)
    y0, y1 = max(0, int(y) - radius), min(height, int(y) + radius)
    patch = image[y0:y1, x0:x1]
    if patch.size == 0:
        return False
    lit = (patch.sum(axis=2) > 90).mean()
    return bool(lit >= floor)


def on_a_grid_line(x: float, y: float, grid: tuple[float, float] = GRID_SPAWN,
                   tolerance: float = 5.0) -> bool:
    """Whether a point lies on a block boundary.

    The region outlines are drawn in the same red as the marks and *along* the block edges, so
    this one geometric test removes them all - including their corners, which survive every
    size and thickness filter because a corner is short and thick.
    """
    grid_x, grid_y = grid
    dx = abs((x - grid_x) % CELL)
    dy = abs((y - grid_y) % CELL)
    return dx <= tolerance or dx >= CELL - tolerance or dy <= tolerance or dy >= CELL - tolerance


def excluded(kind: str, x: float, y: float) -> bool:
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in EXCLUDE.get(kind, []))


def marks(path: Path, min_px: int, max_px: int, max_side: int,
          kind: str = "") -> list[tuple[float, float, int]]:
    """Every annotation mark in an image, as ``(x, y, pixel count)``.

    ``max_side`` drops the long thin blobs: the region outlines are drawn in the same red as
    the dots, and a 100-pixel line is not a mark.
    """
    image = np.asarray(Image.open(path).convert("RGB")).astype(int)
    mask = np.abs(image - np.array(ANNOTATION_RGB)).sum(axis=2) <= COLOUR_TOLERANCE
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found: list[tuple[float, float, int]] = []
    for y0 in range(height):
        for x0 in range(width):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            queue = deque([(y0, x0)])
            seen[y0, x0] = True
            pixels: list[tuple[int, int]] = []
            while queue:
                y, x = queue.popleft()
                pixels.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] \
                                and not seen[ny, nx]:
                            seen[ny, nx] = True
                            queue.append((ny, nx))
            count = len(pixels)
            if not (min_px <= count <= max_px):
                continue
            xs = [p[1] for p in pixels]
            ys = [p[0] for p in pixels]
            # Named apart from the image's own width/height: the flood fill above tests its
            # bounds against those, and shadowing them here silently truncated every blob.
            blob_w = max(xs) - min(xs) + 1
            blob_h = max(ys) - min(ys) + 1
            if max(blob_w, blob_h) > max_side:
                continue
            cx, cy = sum(xs) / count, sum(ys) / count
            if excluded(kind, cx, cy) or on_the_map(image, cx, cy) is False \
                    or on_a_grid_line(cx, cy, GRID_FIGHT if kind == "fight" else GRID_SPAWN):
                continue
            found.append((cx, cy, count))
    return found


def cell_of(x: float, y: float, grid: tuple[float, float] = GRID_SPAWN) -> tuple[int, int]:
    """Which grid cell a point is in, as (column, row) indices."""
    import math

    grid_x, grid_y = grid
    return (int(math.floor((x - grid_x) / CELL)), int(math.floor((y - grid_y) / CELL)))


def code_of(x: float, y: float, grid: tuple[float, float] = GRID_SPAWN) -> str:
    """Where in its block a point sits: ``C``, ``L``/``R``, plus ``U``/``D`` off the middle row.

    Thirds, because that is what a three-by-three description means: the left third is ``L``,
    the middle ``C``, the right ``R``, and similarly for the rows - with the vertical part left
    out when the mark is on the middle row, which is how the player wrote the examples
    (``RU``, ``L``, ``C``).
    """
    grid_x, grid_y = grid
    column, row = cell_of(x, y, grid)
    fx = (x - (grid_x + column * CELL)) / CELL
    fy = (y - (grid_y + row * CELL)) / CELL
    horizontal = "L" if fx < 1 / 3 else "R" if fx > 2 / 3 else "C"
    vertical = "U" if fy < 1 / 3 else "D" if fy > 2 / 3 else ""
    return horizontal + vertical


def area_corner(path: Path, grid: tuple[float, float], floor: float = 0.4) -> tuple[int, int]:
    """The bottom-right-most cell of the drawn area, which is the block the player named.

    Found from the map art rather than from the marks: a corner block need not carry a dot, and
    the fighting map has no dots at all. A cell belongs to the area when enough of it is lit.
    """
    image = np.asarray(Image.open(path).convert("RGB")).astype(int)
    height, width = image.shape[:2]
    grid_x, grid_y = grid
    # (column, row), the same order ``cell_of`` uses: mixing the two transposed the whole
    # table silently, which the cross-check against the live boss map caught.
    best = (0, 0)
    for column in range(int((width - grid_x) // CELL) + 1):
        for row in range(int((height - grid_y) // CELL) + 1):
            x0 = int(grid_x + column * CELL) + 6
            y0 = int(grid_y + row * CELL) + 6
            patch = image[max(0, y0):y0 + int(CELL) - 12, max(0, x0):x0 + int(CELL) - 12]
            if patch.size == 0:
                continue
            if (patch.sum(axis=2) > 90).mean() >= floor and (column, row) > best:
                best = (column, row)
    return best


def clusters(path: Path, min_px: int, max_px: int, max_side: int,
             kind: str = "", grid: tuple[float, float] = GRID_SPAWN)         -> dict[tuple[int, int], str]:
    """One code per block that carries an annotation, weighted by mark size."""
    by_cell: dict[tuple[int, int], list[tuple[float, float, int]]] = defaultdict(list)
    for x, y, count in marks(path, min_px, max_px, max_side, kind):
        by_cell[cell_of(x, y, grid)].append((x, y, count))
    out: dict[tuple[int, int], str] = {}
    for cell, group in by_cell.items():
        total = sum(count for _x, _y, count in group)
        cx = sum(x * count for x, _y, count in group) / total
        cy = sum(y * count for _, y, count in group) / total
        out[cell] = code_of(cx, cy, grid)
    return out


def to_blocks(cells: dict[tuple[int, int], str],
              anchor_cell: tuple[int, int]) -> dict[tuple[int, int], str]:
    """Grid cells to game blocks, from the anchor the player gave.

    ``x`` grows east and ``y`` grows south in the image, which is also how the block grid runs:
    a boss one block north of the player is a lower ``y`` and a higher row number here.
    """
    anchor_column, anchor_row = anchor_cell
    anchor_x, anchor_y = ANCHOR_BLOCK
    out: dict[tuple[int, int], str] = {}
    for (column, row), code in cells.items():
        out[(anchor_x - (anchor_column - column), anchor_y - (anchor_row - row))] = code
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draw", default="", help="write a verification image here")
    args = parser.parse_args()

    bandit_cells = clusters(SPAWN_MAP, 60, 300, 30, "spawn", GRID_SPAWN)
    # A smaller floor for the fighting map: its marks are thin dashes, drawn by hand at a
    # different zoom, and only their cores are pure red. The grid-line test above is what keeps
    # the noise out, not the pixel count.
    wall_cells = clusters(FIGHT_MAP, 5, 400, 40, "fight", GRID_FIGHT)
    bandit_anchor = area_corner(SPAWN_MAP, GRID_SPAWN)
    fight_anchor = area_corner(FIGHT_MAP, GRID_FIGHT)
    print(f"area corner: spawn cell {bandit_anchor}, fight cell {fight_anchor} = block "
          f"{ANCHOR_BLOCK}")

    bandits = to_blocks(bandit_cells, bandit_anchor)
    walls = to_blocks(wall_cells, fight_anchor)
    print(f"{len(bandits)} blocks with a bandit spawn note, {len(walls)} with a wall note")
    shared = set(bandits) & set(walls)
    print(f"{len(shared)} blocks carry both (the bandit note wins for a bandit row)")

    lines = [
        '"""Where in each block the interesting things are - the player\'s own two maps, read.',
        "",
        "Generated by ``tools/build-fieldnotes.py`` from the screenshots in ``docs/evidence/``;",
        "edit that script rather than this file. The two tables say where *inside* a block a mark",
        "sits, as a three-by-three position: the horizontal part is ``L``/``C``/``R`` and the",
        "vertical part is ``U``/``D``, left out on the middle row - so ``RU`` is the top-right of",
        "the block, ``L`` the left edge at mid height, ``C`` the middle.",
        "",
        "* :data:`BANDIT_SPAWNS` - where the ``6 x Bandits`` group appears in that block",
        "  (the player's *Bandits Spawn Locations* map, 2026-10-07);",
        "* :data:`WALLS` - the wall a boss can be trapped against, prefixed ``W``",
        "  (their *Boss Fighting Map*, same day). Green dots on that map are the player's own",
        "  positions and are ignored.",
        "",
        "Both are answered per block, and a row shows one note: the bandit one when the row is a",
        "bandit spawn, the wall one otherwise. The tables are keyed by the game's own block",
        "coordinates, anchored on the block the player named - the bottom-right-most dot of the",
        "bandit map, ``1058,1019``.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "#: block -> position of the `6 x Bandits` spawn inside it",
        "BANDIT_SPAWNS: dict[tuple[int, int], str] = {",
    ]
    for block in sorted(bandits):
        lines.append(f'    ({block[0]}, {block[1]}): "{bandits[block]}",')
    lines += [
        "}",
        "",
        "#: block -> position of the wall to trap a boss against, `W` prefixed",
        "WALLS: dict[tuple[int, int], str] = {",
    ]
    for block in sorted(walls):
        lines.append(f'    ({block[0]}, {block[1]}): "W{walls[block]}",')
    lines += [
        "}",
        "",
        "",
        "def bandit_remark(block) -> str:  # noqa: ANN001",
        '    """Where the bandits stand in this block, or an empty string."""',
        "    return BANDIT_SPAWNS.get((block.x, block.y), \"\")",
        "",
        "",
        "def wall_remark(block) -> str:  # noqa: ANN001",
        '    """The wall to trap a boss against in this block, or an empty string."""',
        "    return WALLS.get((block.x, block.y), \"\")",
        "",
        "",
        "def remark_for(block, bandits: bool) -> str:  # noqa: ANN001",
        '    """The one field note a row gets: the bandit spot for a bandit row, else the wall.',
        "",
        "    One, not two: a block can carry both, and two remarks on one line would push the",
        "    coordinate and the bearing - the fields the row exists for - out of the strip.",
        '    """',
        "    return bandit_remark(block) if bandits else wall_remark(block)",
        "",
    ]
    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(PROJECT_ROOT)}")

    if args.draw:
        for path, cells, colour, label in ((SPAWN_MAP, bandit_cells, (255, 255, 0), "spawn"),
                                           (FIGHT_MAP, wall_cells, (255, 255, 0), "wall")):
            view = Image.open(path).convert("RGB")
            draw = ImageDraw.Draw(view)
            for k in range(-4, 12):
                draw.line([(GRID_X + k * CELL, 0), (GRID_X + k * CELL, view.height)],
                          fill=(0, 220, 255), width=2)
            for k in range(-2, 10):
                draw.line([(0, GRID_Y + k * CELL), (view.width, GRID_Y + k * CELL)],
                          fill=(0, 220, 255), width=2)
            for (column, row), code in cells.items():
                cx = GRID_X + (column + 0.5) * CELL
                cy = GRID_Y + (row + 0.5) * CELL
                draw.rectangle([cx - 26, cy - 14, cx + 26, cy + 14], outline=colour, width=2)
                draw.text((cx - 20, cy - 8), code, fill=colour)
            out = Path(args.draw).with_name(Path(args.draw).stem + f"-{label}.png")
            view.save(out)
            print(f"wrote {out} for checking by eye")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
