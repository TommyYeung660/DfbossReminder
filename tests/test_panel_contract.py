"""Static contracts for the Windows-only overlay and window code.

The overlay window and the game-window locator cannot be executed here - this
machine has no ``user32`` - so the properties that make them safe and correct are
pinned two ways: the style flags have their documented values, and the source that
creates the window is required to pass them. That is the difference between "we
believe the overlay is click-through" and a test that fails if someone drops a flag.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

from dfbossreminder.services import window as window_module
from dfbossreminder.ui import panel as panel_module
from dfbossreminder.ui.panel import Overlay, Row, _rgb

PANEL_SOURCE = Path(panel_module.__file__).read_text(encoding="utf-8")
WINDOW_SOURCE = Path(window_module.__file__).read_text(encoding="utf-8")


def test_the_window_style_flags_have_their_documented_values() -> None:
    assert panel_module.WS_EX_LAYERED == 0x00080000
    assert panel_module.WS_EX_TRANSPARENT == 0x00000020      # clicks pass through
    assert panel_module.WS_EX_TOPMOST == 0x00000008          # stays above the client
    assert panel_module.WS_EX_TOOLWINDOW == 0x00000080       # not in alt-tab
    assert panel_module.WS_EX_NOACTIVATE == 0x08000000       # never takes focus
    assert panel_module.WS_POPUP == 0x80000000


def test_the_overlay_window_is_created_with_every_safety_flag() -> None:
    call = re.search(r"CreateWindowExW\((.*?)\)\n", PANEL_SOURCE, re.DOTALL)
    assert call, "the overlay must create its window with CreateWindowExW"
    styles = call.group(1)
    for flag in ("WS_EX_LAYERED", "WS_EX_TRANSPARENT", "WS_EX_TOPMOST",
                 "WS_EX_TOOLWINDOW", "WS_EX_NOACTIVATE"):
        assert flag in styles, f"the overlay window must be created with {flag}"


def test_the_overlay_is_shown_without_activating_itself() -> None:
    assert "SW_SHOWNOACTIVATE" in PANEL_SOURCE
    assert "SWP_NOACTIVATE" in PANEL_SOURCE


def test_per_pixel_alpha_is_used_so_only_the_readout_is_visible() -> None:
    assert "UpdateLayeredWindow" in PANEL_SOURCE
    assert "ULW_ALPHA" in PANEL_SOURCE
    assert "AC_SRC_ALPHA" in PANEL_SOURCE
    # Premultiplied BGRA is what the blend function expects; the fill divides each
    # channel by 255 for exactly that reason.
    assert "// 255" in PANEL_SOURCE


def test_the_overlay_never_writes_to_the_game() -> None:
    for forbidden in ("WriteProcessMemory", "CreateRemoteThread", "SendInput",
                      "keybd_event", "mouse_event", "PostMessage", "SetForegroundWindow"):
        assert forbidden not in PANEL_SOURCE, f"the overlay must not call {forbidden}"
        assert forbidden not in WINDOW_SOURCE, f"the window locator must not call {forbidden}"


def test_the_window_locator_only_reads() -> None:
    # Measuring the client rectangle must not need focus, so the tools it uses are
    # the read-only ones.
    assert "GetClientRect" in WINDOW_SOURCE
    assert "ClientToScreen" in WINDOW_SOURCE
    assert "OpenProcess" not in WINDOW_SOURCE       # no process handle is needed at all


def test_the_overlay_raises_off_windows_rather_than_silently_doing_nothing() -> None:
    if sys.platform == "win32":
        pytest.skip("this machine is Windows; the guard is not reachable")
    assert panel_module._bind.__name__ == "_bind"
    with pytest.raises(RuntimeError):
        panel_module._bind()


def test_the_window_locator_reports_absence_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("this machine is Windows")
    assert window_module.find_game_window() is None
    assert window_module.screen_rect() is None


def test_a_row_is_just_text_and_a_colour() -> None:
    row = Row("6 x Bandits | 1052 x 1018 | 5LD1")
    assert row.colour == (235, 235, 235)


def test_the_panel_metrics_follow_the_configured_font_size() -> None:
    # A pinned line height would clip a larger font or space a smaller one out, and
    # the font size is a user setting.
    source = PANEL_SOURCE
    assert "line_height = max(10, int(font_size) + LINE_GAP)" in source
    assert "rows_fitting" in source


def test_the_colour_conversion_matches_gdi_channel_order() -> None:
    # GDI wants 0x00BBGGRR, so red is the low byte.
    assert _rgb((255, 0, 0)) == 0x000000FF
    assert _rgb((0, 255, 0)) == 0x0000FF00
    assert _rgb((0, 0, 255)) == 0x00FF0000
    assert _rgb((0x12, 0x34, 0x56)) == 0x00563412


def test_the_hotkey_table_covers_the_function_keys() -> None:
    assert panel_module.VK["F8"] == 0x77
    assert panel_module.VK["F1"] == 0x70
    assert panel_module.VK["F12"] == 0x7B
    assert panel_module.MOD_NOREPEAT == 0x4000      # a held key does not repeat


def test_the_overlay_module_imports_without_windows() -> None:
    # Importing must never bind user32, or the whole package would be unusable on a
    # development machine; only constructing the window does.
    assert Overlay is not None
    source_head = PANEL_SOURCE.split("def _bind")[0]
    assert "WinDLL" not in source_head


def test_the_overlay_checks_that_its_font_really_exists() -> None:
    # CreateFontW silently substitutes an unknown face, and a face without CJK glyphs
    # draws the zh bearing words as blank boxes - which is what happened with
    # Consolas. So the chosen face is verified through GetTextFaceW, and there are
    # CJK-capable fixed-pitch candidates to choose from.
    assert "GetTextFaceW" in PANEL_SOURCE
    assert "MingLiU" in PANEL_SOURCE
    assert "MS Gothic" in PANEL_SOURCE
    assert "Consolas" in PANEL_SOURCE
    assert panel_module.FONT_CANDIDATES[0] != "Consolas"
    assert "Consolas" in panel_module.FONT_CANDIDATES_ASCII


def test_the_overlay_counts_a_cjk_character_as_two_columns() -> None:
    # The other half of the same defect: padding by character count pushed the
    # minutes past the panel.
    from dfbossreminder.ui import view

    assert view.display_width("3右2上") == 6
    assert view.display_width("5LD1") == 4


def test_the_unavailable_path_is_reported_rather_than_hidden() -> None:
    # The presenter in app.py turns a failed overlay into the console and says so;
    # the message that does it is pinned here.
    from dfbossreminder import app

    source = inspect.getsource(app.make_presenter)
    assert "falling back to the console" in source


def test_a_transparent_backing_draws_no_frame() -> None:
    # With nothing behind it, a border and a title rule are stray lines over the game,
    # so they are dropped rather than left floating; the surface is cleared instead.
    assert "self.framed = background[3] > 0" in PANEL_SOURCE
    assert "if self.framed:" in PANEL_SOURCE
    assert "_clear()" in PANEL_SOURCE


def test_a_transparent_backing_shadows_the_text_instead() -> None:
    # GDI cannot outline a glyph, so the shadow is the text drawn in near-black at four
    # one-pixel offsets first. Without it, green text over bright terrain disappears.
    assert "SHADOW_COLOUR" in PANEL_SOURCE
    assert "(-1, 0), (1, 0), (0, -1), (0, 1)" in PANEL_SOURCE
    assert "text_shadow: bool = False" in PANEL_SOURCE


def test_the_line_metrics_follow_the_configured_font_size() -> None:
    # A pinned line height would clip a larger font or space a smaller one out, and the
    # font size is a user setting.
    assert "line_height = max(10, int(font_size) + LINE_GAP)" in PANEL_SOURCE
    assert "rows_fitting" in PANEL_SOURCE


def test_a_cleared_surface_gets_its_glyph_pixels_made_opaque_again() -> None:
    # GDI draws into a 32-bit DIB without touching the alpha byte, so on a cleared
    # surface the glyphs would be drawn and then be invisible, because
    # UpdateLayeredWindow composites by alpha. This is the fix, and the shadow colour is
    # non-black because the test for "we drew this pixel" is a non-zero colour.
    assert "_opaque_glyphs" in PANEL_SOURCE
    assert "row[offset + 3] = 255" in PANEL_SOURCE
    assert panel_module.SHADOW_COLOUR != (0, 0, 0)
    assert "last_text_y" in PANEL_SOURCE
