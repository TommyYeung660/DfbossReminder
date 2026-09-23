"""The half of the window capture that can be checked without Windows.

``tools/pc/capture-window.py`` is GDI on one side and byte arithmetic on the other. The
arithmetic - turning a top-down 32-bit BGRA buffer into a 24-bit BMP file - is where a
silent mistake would produce an image that looks almost right: a picture with the rows
upside down, or with the red and blue channels swapped, is still a plausible picture.

Only the pure function is tested here, and the GDI calls are pinned by their flags and
their binding, the way the rest of this project's Windows-only code is.
"""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOL = PROJECT_ROOT / "tools" / "pc" / "capture-window.py"


def load_tool():  # noqa: ANN202
    """The tool as a module. Its name has a hyphen, so it cannot be imported normally."""
    spec = importlib.util.spec_from_file_location("capture_window", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_bmp_header_matches_the_bytes_that_follow_it() -> None:
    tool = load_tool()
    pixels = bytes(2 * 2 * 4)                       # a 2x2 black image
    data = tool.to_bmp(pixels, 2, 2)
    assert data[:2] == b"BM"
    (size, _reserved) = struct.unpack("<IH", data[2:8])
    assert size == len(data), "the size in the header must be the size of the file"
    offset = struct.unpack("<I", data[10:14])[0]
    assert offset == 14 + 40
    assert data[14:18] == struct.pack("<I", 40), "the info header size"
    width, height, planes, bits = struct.unpack("<iiHH", data[18:30])
    assert (width, height, planes, bits) == (2, 2, 1, 24)
    # Positive height means bottom-up, which is what the row order below relies on.
    assert height > 0
    assert struct.unpack("<I", data[30:34])[0] == 0, "biCompression must be BI_RGB"


def test_the_rows_are_written_bottom_up() -> None:
    tool = load_tool()
    # Top row blue, bottom row red, as BGRA. The file has to hold the bottom row first.
    pixels = b"\xff\x00\x00\xff" + b"\x00\x00\xff\xff"
    data = tool.to_bmp(pixels, 1, 2)
    body = data[14 + 40:]
    # One pixel per row, so each row is three bytes plus one padding byte.
    assert len(body) == 8
    assert body[0:3] == b"\x00\x00\xff", "the last source row comes first in the file"
    assert body[4:7] == b"\xff\x00\x00", "and the first source row comes last"


def test_the_channels_stay_bgr_and_the_alpha_is_dropped() -> None:
    tool = load_tool()
    # One pixel, alpha 0x7F: 24-bit BMP has no alpha, and the byte order must not change.
    data = tool.to_bmp(b"\x33\x22\x11\x7f", 1, 1)
    assert len(data) == 14 + 40 + 4
    assert data[14 + 40:14 + 40 + 3] == b"\x33\x22\x11"


def test_every_row_is_padded_to_a_four_byte_boundary() -> None:
    tool = load_tool()
    # Three pixels wide is nine bytes, which has to be padded to twelve.
    data = tool.to_bmp(bytes(3 * 4), 3, 1)
    assert len(data) == 14 + 40 + 12
    assert data[-3:] == b"\x00\x00\x00"
    assert struct.unpack("<I", data[34:38])[0] == 12      # biSizeImage
    # Two pixels wide is six bytes, padded to eight.
    assert len(tool.to_bmp(bytes(2 * 4), 2, 1)) == 14 + 40 + 8


def test_the_gdi_calls_are_bound_to_the_library_that_has_them() -> None:
    # PrintWindow and GetWindowDC are user32; the DIB calls are gdi32. Binding one on the
    # wrong library is a mistake this project has already made once, and it only shows up
    # as an AttributeError on the machine that has the real DLLs.
    source = TOOL.read_text(encoding="utf-8")
    body = source[source.index("def bind("):source.index("def find_windows(")]
    # The two WinDLL lines sit next to each other and everything is bound after them, so
    # the library is read from each binding line rather than from where the slicing lands.
    bound: dict[str, str] = {}
    for line in body.splitlines():
        text = line.strip()
        for library in ("user32", "gdi32"):
            if text.startswith(f"{library}.") and ".argtypes" in text:
                bound[text.split(".")[1]] = library
    assert bound, "no bindings were found, so this test is checking nothing"
    for name in ("FindWindowW", "GetWindowRect", "PrintWindow", "GetWindowDC", "ReleaseDC",
                 "EnumWindows", "IsWindowVisible", "GetWindowTextW", "GetWindowTextLengthW"):
        assert bound.get(name) == "user32", f"{name} belongs on user32, not {bound.get(name)}"
    for name in ("CreateCompatibleDC", "CreateCompatibleBitmap", "GetDIBits",
                 "DeleteObject", "DeleteDC", "SelectObject"):
        assert bound.get(name) == "gdi32", f"{name} belongs on gdi32, not {bound.get(name)}"
    # Every call that hands back a handle must also have its return type declared: an
    # undeclared restype is c_int, and a 32-bit handle on 64-bit Windows is a truncated
    # one, which fails later as "invalid DC" with no hint of where it happened.
    for name in list(bound):
        after = body[body.index(f".{name}.argtypes"):]
        # The declaration can wrap onto the next line, so the search is not line-based.
        assert ".restype" in after[:after.index("\n\n") + 400], f"{name} has no restype"


def test_the_capture_never_activates_the_window() -> None:
    # Bringing the settings window to the front would take the focus away from the game,
    # which is a much worse outcome than a missing screenshot. PrintWindow draws into a
    # device context instead, and nothing in this tool may raise or focus a window.
    source = TOOL.read_text(encoding="utf-8")
    for forbidden in ("SetForegroundWindow", "SetActiveWindow", "ShowWindow", "BringWindowToTop",
                      "SetFocus", "WM_ACTIVATE"):
        assert forbidden not in source, f"{forbidden} would steal the focus"
    # And the render-full-content flag is tried first: a window that draws itself with a
    # surface comes out blank without it.
    assert source.index("PW_RENDERFULLCONTENT = 0x00000002") > 0
    assert source.index("(PW_RENDERFULLCONTENT, \"render-full-content\")") < \
        source.index("(PW_CLIENTONLY, \"client-only\")")
