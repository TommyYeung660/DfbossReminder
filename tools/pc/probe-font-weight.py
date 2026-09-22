"""Measure what the font weight request and the shadow actually change in the pixels.

The readout asks for ``font-weight: 300``. GDI answers ``CreateFontW`` with whatever
face the family has, and the client's HUD font declares exactly one face, so the
question "did the text get lighter because of the weight number?" cannot be settled by
reading the font's metadata - the metadata says there is nothing lighter to select, and
GDI's ``GetObjectW`` nevertheless echoes back the number it was asked for on this
machine.

So this probe stops asking and measures. It draws one identical line through the same
code path the overlay uses, and reports, per combination:

* the weight ``CreateFontW`` was asked for and the weight ``GetObjectW`` gives back;
* whether the drawn pixels are *identical* to another combination's (same raster, or
  same 32-bit surface, as an MD5 of the raw DIB);
* how many pixels the text occupies ("ink") - the quantity the eye reads as weight.

Two shadow styles are compared as well: the single drop shadow the overlay uses now,
and the four-offset shadow it used before, drawn here by the probe so the old
behaviour is reproduced rather than remembered.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\probe-font-weight.py
    py -3 tools\\pc\\probe-font-weight.py --font-cache %USERPROFILE%\\.dfbossreminder\\game-font.ttf
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dfbossreminder.domain.settings import DEFAULT_COLOURS, hex_to_rgb  # noqa: E402
from dfbossreminder.services.gamefont import CACHE_NAME, FONT_FAMILY  # noqa: E402
from dfbossreminder.ui import panel as panel_module  # noqa: E402
from dfbossreminder.ui.panel import (  # noqa: E402
    DT_END_ELLIPSIS,
    DT_NOPREFIX,
    DT_RIGHT,
    DT_SINGLELINE,
    SHADOW_COLOUR,
    Overlay,
)

LINE_COLOUR = hex_to_rgb(DEFAULT_COLOURS["list"])

WEIGHTS = (100, 200, 300, 400, 500, 700, 900)
SHADOWS = ("single", "four", "none")
LINE = "1 x Evolved Longarms + 1 x Irradiated | 1054 x 1016 | 3LU1"
WIDTH = 340
HEIGHT = 40


def raw_surface(panel: Overlay) -> bytes:
    """The overlay's own 32-bit DIB, as bytes - the exact pixels it would present."""
    size = panel.width * panel.height * 4
    return ctypes.string_at(panel.bits, size)


def ink(panel: Overlay) -> int:
    """How many pixels the text occupies.

    The surface is cleared to zero and the only thing drawn on it is this one line, so
    "any non-zero colour channel" is exactly "the text is here" - the same test
    :meth:`Overlay._opaque_glyphs` uses to decide which pixels are ours.
    """
    pixels = raw_surface(panel)
    return sum(1 for offset in range(0, len(pixels), 4) if any(pixels[offset:offset + 3]))


def draw_four_offsets(panel: Overlay, text: str, box: tuple[int, int, int, int],
                      colour: tuple[int, int, int], flags: int) -> None:
    """The shadow the overlay used before this session: the text drawn on all four sides.

    Reproduced here rather than described, so the "did four offsets read as bold?"
    question is answered with the same pixels the old code produced.
    """
    left, top, right, bottom = box
    rect = panel_module.wintypes.RECT
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        panel.gdi32.SetTextColor(panel.mem_dc, panel_module._rgb(SHADOW_COLOUR))
        panel.user32.DrawTextW(panel.mem_dc, text, -1,
                              ctypes.byref(rect(left + dx, top + dy, right, bottom)), flags)
    panel.gdi32.SetTextColor(panel.mem_dc, panel_module._rgb(colour))
    panel.user32.DrawTextW(panel.mem_dc, text, -1,
                           ctypes.byref(rect(left, top, right, bottom)), flags)


def render(weight: int, shadow: str, cache: Path | None) -> Overlay:
    """One line, drawn as the overlay draws it, at this weight and shadow style."""
    # A transparent background is what makes ``framed`` false, which is the mode whose
    # text-only surface these questions are about.
    panel = Overlay(left=0, top=0, width=WIDTH, height=HEIGHT, background=(0, 0, 0, 0),
                  font_size=10, font_weight=weight, text_shadow=(shadow == "single"),
                  align="right")
    if cache is not None and cache.is_file():
        face = panel.load_private_font(str(cache), FONT_FAMILY)
        if face:
            panel.set_face(face)
    panel._clear()
    panel.gdi32.SelectObject(panel.mem_dc, panel.font)
    flags = DT_RIGHT | DT_SINGLELINE | DT_NOPREFIX | DT_END_ELLIPSIS
    box = (8, 2, WIDTH - 8, 2 + panel.line_height)
    if shadow == "four":
        draw_four_offsets(panel, LINE, box, LINE_COLOUR, flags)
    else:
        panel._text(LINE, *box, LINE_COLOUR, flags)
    return panel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-cache", default="",
                        help="the extracted game font; empty means use it if the default exists")
    parser.add_argument("--dump", default="", help="write the surfaces here as one BMP per row")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this probe only runs on Windows", file=sys.stderr)
        return 1

    cache = Path(args.font_cache) if args.font_cache else (
        Path.home() / ".dfbossreminder" / CACHE_NAME)
    print(f"font cache: {cache} {'(present)' if cache.is_file() else '(absent - system face)'}")
    print(f"line: {LINE!r}")
    print()

    rows: list[dict] = []
    for shadow in SHADOWS:
        for weight in WEIGHTS:
            panel = render(weight, shadow, cache)
            surface = raw_surface(panel)
            rows.append({
                "shadow": shadow,
                "asked": weight,
                "resolved": panel.resolved_weight,
                "face": panel.font_face,
                "ink": ink(panel),
                "md5": hashlib.md5(surface).hexdigest(),
            })
            panel.close()

    print(f"{'shadow':<8}{'asked':>6}{'back':>6}  {'ink':>6}  {'face':<14}md5")
    for row in rows:
        print(f"{row['shadow']:<8}{row['asked']:>6}{row['resolved']:>6}  "
              f"{row['ink']:>6}  {row['face'][:13]:<14}{row['md5'][:12]}")

    print()
    problems: list[str] = []

    # 1. Does the requested number change any drawn pixel, and from where?
    for shadow in SHADOWS:
        group = [row for row in rows if row["shadow"] == shadow]
        bands: list[dict] = []
        for row in group:
            if bands and bands[-1]["md5"] == row["md5"]:
                bands[-1]["weights"].append(row["asked"])
                bands[-1]["resolved"].add(row["resolved"])
            else:
                bands.append({"md5": row["md5"], "ink": row["ink"],
                              "weights": [row["asked"]], "resolved": {row["resolved"]}})
        parts = ", ".join(
            f"{band['weights'][0]}-{band['weights'][-1]} render identically "
            f"(ink {band['ink']}, GDI reports {sorted(band['resolved'])})"
            for band in bands)
        print(f"[shadow={shadow}] {len(bands)} distinct renders across "
              f"{len(WEIGHTS)} weights: {parts}")
        if len(bands) == 1:
            print("    -> the weight number changes nothing for this font at all")
        else:
            floor_ = bands[0]["weights"]
            print(f"    -> the {floor_[0]}-{floor_[-1]} band is the lightest this font can "
                  f"be drawn; a request below it buys nothing and 700+ makes GDI "
                  f"synthesise a heavier face")

    single = next(row for row in rows if row["shadow"] == "single" and row["asked"] == 300)
    four = next(row for row in rows if row["shadow"] == "four" and row["asked"] == 300)
    none = next(row for row in rows if row["shadow"] == "none" and row["asked"] == 300)

    # 2. The weight the readout asks for has to be at the floor, or it is asking the font
    #    for something it cannot do and the request is doing nothing.
    floor_weights = {row["asked"] for row in rows
                     if row["shadow"] == "none" and row["md5"] == none["md5"]}
    if single["asked"] in floor_weights:
        print(f"\nthe weight the readout uses ({single['asked']}) is inside the lightest band "
              f"({min(floor_weights)}-{max(floor_weights)}): it is at the floor, not merely "
              f"below some heavier face")
    else:
        problems.append(f"the readout asks for {single['asked']}, which does not render "
                        f"like the lightest band {sorted(floor_weights)}")

    # 3. What did the single drop shadow buy over the four-offset one?
    if none["ink"]:
        print(f"ink at weight 300: no shadow {none['ink']}, single {single['ink']} "
              f"({single['ink'] / none['ink']:.2f}x), four-offset {four['ink']} "
              f"({four['ink'] / none['ink']:.2f}x)")
        print(f"the four-offset shadow surrounds every glyph with dark fringe on all four "
              f"sides: {four['ink'] - single['ink']} more pixels than the single offset "
              f"({(four['ink'] / single['ink'] - 1) * 100:.0f}% more ink), and the single "
              f"offset keeps the fringe on one side only")
        if four["ink"] <= single["ink"]:
            problems.append("the four-offset shadow did not add ink: the 'it read as "
                            "emboldening' explanation is wrong and must be re-investigated")

    # 4. Does the shadow change the glyph pixels themselves, or only surround them?
    if single["md5"] == none["md5"]:
        problems.append("the shadow changed nothing at all, so it is not being drawn")
        print("\nthe shadow made no difference to the surface: it is not being drawn")

    if args.dump:
        out = Path(args.dump)
        out.mkdir(parents=True, exist_ok=True)
        for shadow in SHADOWS:
            for weight in (300, 400):
                panel = render(weight, shadow, cache)
                target = out / f"weight{weight}-shadow-{shadow}.bmp"
                panel.dump(str(target))
                panel.close()
        print(f"\nwrote surfaces to {out}")

    if problems:
        print("\nPROBLEMS:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
