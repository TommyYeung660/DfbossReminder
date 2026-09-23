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
    # Measuring the client rectangle must not need focus, so the tools it uses are the
    # read-only ones. It does now open the process, on purpose: the client's own HUD
    # font is taken from the installation the running executable came from. That handle
    # is a *query* handle - asking for the image path needs no memory access at all -
    # and the test pins that, because widening it to PROCESS_VM_READ or a write right
    # would be a different project.
    assert "GetClientRect" in WINDOW_SOURCE
    assert "ClientToScreen" in WINDOW_SOURCE
    assert "PROCESS_QUERY_LIMITED_INFORMATION = 0x1000" in WINDOW_SOURCE
    assert "PROCESS_VM_READ" not in WINDOW_SOURCE
    assert "PROCESS_VM_WRITE" not in WINDOW_SOURCE
    assert "PROCESS_VM_OPERATION" not in WINDOW_SOURCE
    assert "WriteProcessMemory" not in WINDOW_SOURCE


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


def test_a_row_with_chinese_is_drawn_in_a_face_that_can_draw_it() -> None:
    # The client's own HUD font (VIPER NORA) has no CJK glyphs, so the header and the
    # notes would be a row of empty boxes beside boss lines that look perfect. Two faces
    # are kept and each row picks by its content.
    assert panel_module.needs_cjk("6 x Bandits | 1052 x 1018 | 5LD1") is False
    assert panel_module.needs_cjk("20 格內") is True
    assert panel_module.needs_cjk("）") is True           # fullwidth punctuation too
    assert "font_cjk if needs_cjk(text) else self.font" in PANEL_SOURCE
    assert "self.cjk_face != self.font_face" in PANEL_SOURCE


def test_the_game_font_is_loaded_privately_and_never_installed() -> None:
    # FR_PRIVATE loads the face for this process only: nothing is installed system-wide
    # and the player's font list is untouched. The face name is read back, because
    # asking for the wrong spelling silently gets a substitute.
    assert panel_module.FR_PRIVATE == 0x10
    assert "AddFontResourceExW" in PANEL_SOURCE
    assert "RemoveFontResourceExW" in PANEL_SOURCE
    assert "GetTextFaceW" in PANEL_SOURCE
    # And nothing in this project may install a font for the whole machine.
    for forbidden in ("WM_FONTCHANGE", "AddFontMemResourceEx"):
        assert forbidden not in PANEL_SOURCE


def test_the_window_class_name_cannot_collide_between_overlays() -> None:
    # A window class name is unique per process, and RegisterClassW refuses a repeat with
    # 1410. Naming the class after the object's address only looked unique: the address
    # is reused once the first overlay is freed, and the 16-bit slice collided often
    # enough that the probe's second overlay failed to open. A counter cannot repeat.
    assert "itertools.count" in PANEL_SOURCE
    assert "_CLASS_SEQ" in PANEL_SOURCE
    assert re.search(r"_class_name = f\"[^\"]*\{os\.getpid\(\)\}_\{next\(_CLASS_SEQ\)\}\"",
                     PANEL_SOURCE), "the class name must be unique per instance"
    assert "id(self)" not in PANEL_SOURCE, "an address is not an identity"


def test_the_window_class_is_released_with_the_window() -> None:
    # The class outlives DestroyWindow, so a process that opens and closes overlays leaks
    # class names until one collides. Unregistering it in close() is the other half of
    # the fix above.
    assert "UnregisterClassW" in PANEL_SOURCE
    body = PANEL_SOURCE[PANEL_SOURCE.index("    def close("):]
    body = body[:body.index("\ndef ")]
    assert "DestroyWindow" in body and "UnregisterClassW" in body
    assert body.index("DestroyWindow") < body.index("UnregisterClassW")


def test_an_empty_title_leaves_no_band_above_the_rows() -> None:
    # The in-game window draws no title, and the window is auto-sized and anchored by its
    # top edge, so reserving a title-sized gap would show as a strip of nothing. The band
    # is the title or a two-pixel margin, and it is what the height and the row count are
    # derived from.
    class FakeOverlay:
        title_height = 18

    fake = FakeOverlay()
    fake._title = ""
    assert panel_module.Overlay.title_band.fget(fake) == 2
    fake._title = "DFBossReminder  1057,1017  3 個附近"
    assert panel_module.Overlay.title_band.fget(fake) == 21
    # Both the height and the row count have to follow the band, not the title height:
    # with a title-sized reserve left in, the last row would be clipped.
    assert "return self.title_band + rows * self.line_height + 2" in PANEL_SOURCE
    assert "available = self.height - self.title_band - 2" in PANEL_SOURCE
    assert "y = self.title_band" in PANEL_SOURCE
    assert "if self._title:" in PANEL_SOURCE


def test_the_title_rule_is_not_drawn_without_a_title() -> None:
    # It would land on the top border of an opaque panel.
    body = PANEL_SOURCE[PANEL_SOURCE.index("    def _outline("):]
    body = body[:body.index("\ndef ")]
    assert body.index("if not self._title:") < body.index("self.title_height - 2")


def test_the_weight_is_reported_because_it_is_only_a_request() -> None:
    # The client's HUD font ships one face (OS/2 usWeightClass 400, subfamily
    # "Regular"), so there is no lighter outline for 300 to select. GDI nonetheless
    # echoes the requested 300 back through GetObjectW on the game PC, which is why the
    # readout says what was asked for next to what came back instead of claiming the
    # drawn strokes are that weight - the probe measures the pixels for that question.
    assert "GetObjectW" in PANEL_SOURCE
    assert "resolved_weight" in PANEL_SOURCE
    assert "lfWeight" in PANEL_SOURCE
    assert "asked" in PANEL_SOURCE
    # 600 was the old hard-coded weight, which this font can never provide.
    assert "0, 0, 0, 600, 0, 0, 0" not in PANEL_SOURCE


def test_the_shadow_is_a_single_offset_not_four() -> None:
    # Four offsets put shadow on every side of every glyph. That fills the gaps between
    # stems and reads as emboldening, which is what made a weight-300 request look heavy.
    # The probe (tools/pc/probe-font-weight.py) counts the pixels; this pins the shape.
    body = PANEL_SOURCE[PANEL_SOURCE.index("def _text("):]
    body = body[:body.index("def _update_layered_window")]
    offsets = [line.strip() for line in body.splitlines()
               if "left +" in line or "left -" in line or "top -" in line]
    assert offsets == ["ctypes.byref(wintypes.RECT(left + 1, top + 1,"], offsets
    # One rectangle, one offset: a second RECT would be another shadow pass.
    assert body.count("wintypes.RECT") == 2, "one rect for the shadow, one for the glyphs"


def test_the_alignment_is_a_gdi_flag() -> None:
    assert panel_module.ALIGN_FLAGS["right"] == panel_module.DT_RIGHT == 0x00000002
    assert panel_module.ALIGN_FLAGS["left"] == panel_module.DT_LEFT == 0
    assert "ALIGN_FLAGS[self.align]" in PANEL_SOURCE
    # An unknown alignment must not silently become right-aligned text drawn left.
    assert 'self.align = align if align in ALIGN_FLAGS else "right"' in PANEL_SOURCE


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
    # GDI cannot outline a glyph, so the shadow is the text drawn in near-black offset by
    # one pixel first. Without it, green text over bright terrain disappears.
    assert "SHADOW_COLOUR" in PANEL_SOURCE
    assert "(left + 1, top + 1," in PANEL_SOURCE
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
