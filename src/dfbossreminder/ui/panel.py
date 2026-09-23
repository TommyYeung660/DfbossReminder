"""A layered, click-through, always-on-top window that draws the boss readout.

This is the one place the project draws anything, and it is deliberately built so
that it cannot interfere with play:

* ``WS_EX_TRANSPARENT``   - a click passes straight through to the game;
* ``WS_EX_NOACTIVATE``    - it never takes focus, so the game keeps its input;
* ``WS_EX_TOOLWINDOW``    - it stays out of the taskbar and the alt-tab list;
* ``WS_EX_TOPMOST``       - it stays above the client;
* per-pixel alpha via ``UpdateLayeredWindow`` - only the text and the backing are
  visible, not a rectangle of opaque window.

It reads no game state and sends no input; it draws a list of lines it is handed.
That is what makes the in-game mode (the fourth requirement) the same code as the
panel mode with a different anchor: the window is placed over the client's
rectangle either way, and the player sees the readout where the game's own buff
row is.

Every Windows call is bound inside a function, so this module imports and its
contract tests run on a machine that has no ``user32`` at all.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import struct
import sys
import unicodedata
from ctypes import wintypes
from dataclasses import dataclass

from .layout import place

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0
TRANSPARENT = 1
DEFAULT_CHARSET = 1

DT_LEFT = 0x00000000
DT_RIGHT = 0x00000002
DT_CENTER = 0x00000001
ALIGN_FLAGS = {"left": DT_LEFT, "right": DT_RIGHT, "center": DT_CENTER}
DT_SINGLELINE = 0x00000020
DT_NOPREFIX = 0x00000800
DT_END_ELLIPSIS = 0x00008000

# The game's HUD is drawn light-on-dark, so the readout keeps the same contrast.
# The readout mixes ASCII with the zh bearing words, so the font must have both and
# must be fixed-pitch or the columns drift. Consolas has no CJK glyphs at all: with
# it the bearing words came out as blank boxes and the double-width characters pushed
# the minutes past the panel, where the ellipsis ate them. These candidates are all
# fixed-pitch and CJK-capable, most specific first; the chosen one is verified with
# GetTextFaceW rather than assumed, because CreateFontW silently substitutes a font
# it does not have.
FONT_CANDIDATES = ("MingLiU", "MS Gothic", "SimSun", "Microsoft JhengHei", "Consolas")
FONT_CANDIDATES_ASCII = ("Consolas", "Courier New")

FR_PRIVATE = 0x10          # load a font for this process only, never system-wide
DEFAULT_BACKGROUND = (14, 13, 11, 214)
# Near-black rather than pure black, and not a style choice: with a transparent
# backing the glyphs are made opaque by the rule "anything we drew has a non-zero
# colour" (see ``_opaque_glyphs``), so a pure black shadow would be drawn and then
# thrown away.
SHADOW_COLOUR = (12, 12, 12)
DEFAULT_BORDER = (46, 74, 46)
DEFAULT_TITLE = (25, 200, 25)
FONT_FACE = "Consolas"

# Line metrics are derived from the font size rather than pinned, because the size
# is a user setting: a 12 px readout and an 18 px one cannot share a hard-coded row
# height without either clipping the tall one or spacing the short one out.
LINE_GAP = 5
TITLE_GAP = 8

# A window class name has to be unique within the process, and it has to stay unique
# after an overlay is closed and another opens. Deriving it from the object's address
# only looked unique: addresses are reused, and a 16-bit slice of one collided often
# enough that the second overlay of a run failed to open. A counter cannot repeat.
_CLASS_SEQ = itertools.count(1)


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _LOGFONTW(ctypes.Structure):
    """What ``GetObjectW`` fills in for a font, so the weight GDI chose can be read."""

    _fields_ = [("lfHeight", ctypes.c_long), ("lfWidth", ctypes.c_long),
                ("lfEscapement", ctypes.c_long), ("lfOrientation", ctypes.c_long),
                ("lfWeight", ctypes.c_long), ("lfItalic", ctypes.c_byte),
                ("lfUnderline", ctypes.c_byte), ("lfStrikeOut", ctypes.c_byte),
                ("lfCharSet", ctypes.c_byte), ("lfOutPrecision", ctypes.c_byte),
                ("lfClipPrecision", ctypes.c_byte), ("lfQuality", ctypes.c_byte),
                ("lfPitchAndFamily", ctypes.c_byte), ("lfFaceName", ctypes.c_wchar * 32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def needs_cjk(text: str) -> bool:
    """Whether this text contains a character the client's HUD font cannot draw.

    East Asian Wide and Fullwidth are the two categories a CJK face is needed for;
    everything else - ASCII, the punctuation this project uses - is in both faces.
    """
    return any(unicodedata.east_asian_width(char) in ("W", "F") for char in text)


@dataclass(frozen=True)
class Row:
    """One line of the readout: its text and its colour."""

    text: str
    colour: tuple[int, int, int] = (235, 235, 235)


def _bind():  # noqa: ANN202 - ctypes handles
    """Declare every prototype that takes a handle.

    Without ``argtypes`` ctypes passes a 64-bit handle as a C int, which dies with
    "int too long to convert" - every handle here is a pointer.
    """
    if sys.platform != "win32":
        raise RuntimeError("the overlay needs Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                       wintypes.HINSTANCE, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_long
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p,
                                 wintypes.UINT]
    user32.DrawTextW.restype = ctypes.c_int
    user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.c_void_p,
                                           ctypes.c_void_p, wintypes.HDC, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkMode.restype = ctypes.c_int
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
    gdi32.SetTextColor.restype = wintypes.DWORD
    gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.DWORD, wintypes.LPCWSTR]
    gdi32.CreateFontW.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    # GetTextFaceW lives in gdi32, not user32 - asking user32 for it fails the whole
    # overlay with "function not found".
    gdi32.GetTextFaceW.argtypes = [wintypes.HDC, ctypes.c_int, wintypes.LPWSTR]
    gdi32.GetTextFaceW.restype = ctypes.c_int
    gdi32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.AddFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    gdi32.AddFontResourceExW.restype = ctypes.c_int
    gdi32.RemoveFontResourceExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    gdi32.RemoveFontResourceExW.restype = wintypes.BOOL

    return user32, gdi32


def _rgb(colour: tuple[int, int, int]) -> int:
    """GDI wants ``0x00BBGGRR``, not the ``R, G, B`` this project passes around."""
    red, green, blue = colour
    return (red & 0xFF) | ((green & 0xFF) << 8) | ((blue & 0xFF) << 16)


def composite_bmp_rows(raw: bytes, width: int, height: int,
                       backdrop: tuple[int, int, int] = (96, 96, 96)) -> bytes:
    """The DIB's pixels as 24-bit BMP rows, composited over ``backdrop``.

    Pure byte arithmetic, so the one thing that can go wrong silently can be tested on a
    machine with no GDI: the **channel order**. The surface is BGRA and a 24-bit BMP is
    BGR, so the bytes pass through in order - writing them as RGB instead swaps red and
    blue, which is invisible for as long as every colour in use has R equal to B. Every
    green readout this project produced hid it, and the first red style rule showed the
    rows as blue.

    BMP rows run bottom-up and are padded to a four-byte boundary.
    """
    row_size = ((width * 3 + 3) // 4) * 4
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        start = y * width * 4
        row = bytearray()
        for x in range(width):
            offset = start + x * 4
            blue, green, red, alpha = raw[offset:offset + 4]
            if alpha == 255:
                row += bytes((blue, green, red))
            else:
                # Premultiplied BGRA, so the stored channels are already the source terms.
                # Clamped: a diagnostic must not be able to fail on a pixel.
                inverse = 255 - alpha
                row += bytes((
                    min(255, blue + backdrop[2] * inverse // 255),
                    min(255, green + backdrop[1] * inverse // 255),
                    min(255, red + backdrop[0] * inverse // 255)))
        row += bytes(row_size - len(row))
        pixels += row
    return bytes(pixels)


class Overlay:
    """A topmost, click-through layered window that draws rows of text."""

    def __init__(
        self,
        left: int,
        top: int,
        width: int,
        height: int,
        background: tuple[int, int, int, int] = DEFAULT_BACKGROUND,
        border: tuple[int, int, int] = DEFAULT_BORDER,
        title_colour: tuple[int, int, int] = DEFAULT_TITLE,
        font_size: int = 14,
        font_face: str = "",
        prefer_ascii: bool = False,
        text_shadow: bool = False,
        align: str = "right",
        cjk_face: str = "",
        font_weight: int = 300,
    ) -> None:
        self.user32, self.gdi32 = _bind()
        self.width, self.height = int(width), int(height)
        self.left, self.top = int(left), int(top)
        self.background = background
        self.border = border
        self.title_colour = title_colour
        self.text_shadow = text_shadow
        self.align = align if align in ALIGN_FLAGS else "right"
        # A fully transparent backing means the readout is text only: a frame or a
        # title rule with nothing behind it is just stray lines over the game, so both
        # are dropped rather than left floating.
        self.framed = background[3] > 0
        self.line_height = max(10, int(font_size) + LINE_GAP)
        self.title_height = max(14, int(font_size) + TITLE_GAP)
        self._rows: tuple[Row, ...] = ()
        self._title = ""
        self.face_missing = False
        self.last_text_y = 0
        self.loaded_font_path = ""
        self.font_size = int(font_size)
        self.font_weight = int(font_weight)
        self.resolved_weight = 0
        self._class_name = f"DFBossReminderOverlay{os.getpid()}_{next(_CLASS_SEQ)}"

        self._register_class()
        self.hwnd = self.user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            self._class_name, "DFBossReminder", WS_POPUP,
            self.left, self.top, self.width, self.height, None, None, None, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        self._create_buffer(font_size, font_face, prefer_ascii)
        self.user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.present()

    # -------------------------------------------------------------------- window
    def _register_class(self) -> None:
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        def _proc(hwnd, message, wparam, lparam):  # noqa: ANN001, ANN202
            return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._wndproc = WNDPROC(_proc)

        class _WNDCLASS(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        window_class = _WNDCLASS()
        window_class.lpfnWndProc = self._wndproc
        window_class.lpszClassName = self._class_name
        if not self.user32.RegisterClassW(ctypes.byref(window_class)):
            raise OSError(f"RegisterClassW failed: {ctypes.get_last_error()}")

    def _create_buffer(self, font_size: int, font_face: str = "", prefer_ascii: bool = False,
                       cjk_face: str = "") -> None:
        self.screen_dc = self.user32.GetDC(None)
        self.mem_dc = self.gdi32.CreateCompatibleDC(self.screen_dc)
        header = _BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.bmiHeader.biWidth = self.width
        header.bmiHeader.biHeight = -self.height            # top-down
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self.bitmap = self.gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(header),
                                                  DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        self.bits = bits.value
        if not self.bitmap or not self.bits:
            raise OSError("could not create the overlay's DIB section")
        self.gdi32.SelectObject(self.mem_dc, self.bitmap)
        self.gdi32.SetBkMode(self.mem_dc, TRANSPARENT)
        self.prefer_ascii = prefer_ascii
        candidates = FONT_CANDIDATES_ASCII if prefer_ascii else FONT_CANDIDATES
        # Two faces, because the client's own HUD font has no CJK glyphs: the boss
        # lines are drawn in the game's face so they look like the game, and a row with
        # Chinese in it (the header, the notes) is drawn in a face that has them rather
        # than as a row of empty boxes.
        self.font_face = font_face or self._pick_face(font_size, candidates)
        # The CJK face is probed as well, even when it is handed in: a face the
        # machine does not have must not end up as the one that draws the Chinese.
        requested_cjk = cjk_face or (self.font_face if not prefer_ascii else "")
        whole_candidates = ((requested_cjk,) if requested_cjk else ()) + FONT_CANDIDATES
        self.cjk_face = self._pick_face(font_size, whole_candidates)
        self.font = self._create_font(font_size, self.font_face)
        self.font_cjk = (self._create_font(font_size, self.cjk_face)
                         if self.cjk_face != self.font_face else self.font)
        self.resolved_weight = self.resolved_weight_of(self.font)
        self.blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    def set_face(self, face: str) -> None:
        """Use this face for the ASCII rows, releasing the one it replaces.

        The client's font is loaded through the window (confirming a face needs a device
        context), so it arrives after construction. Replacing the handle without
        deleting the old one would leak one GDI object per placement.
        """
        if not face or face == self.font_face:
            return
        previous = self.font
        self.font_face = face
        self.font = self._create_font(self.font_size, face)
        self.resolved_weight = self.resolved_weight_of(self.font)
        if previous and previous not in (0, self.font_cjk):
            self.gdi32.DeleteObject(previous)
        if self.cjk_face == face:
            self.font_cjk = self.font

    def load_private_font(self, path, family: str) -> str | None:  # noqa: ANN001
        """Load a font file for this process only, and return the face name GDI gave.

        ``FR_PRIVATE`` means the font exists for this process and nowhere else - the
        player's font list is untouched and nothing is installed. The face name is read
        back rather than assumed, because it is the font's own choice: asking for the
        wrong spelling silently gets a substitute.
        """
        try:
            added = self.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, None)
        except (AttributeError, OSError):
            return None
        if not added:
            return None
        face = self._confirm_face(self.font_size, family)
        if face:
            self.loaded_font_path = str(path)
        return face

    def _confirm_face(self, size: int, face: str) -> str | None:
        """The face name GDI actually selected, or ``None`` when it substituted."""
        font = self._create_font(size, face)
        if not font:
            return None
        previous = self.gdi32.SelectObject(self.mem_dc, font)
        buffer = ctypes.create_unicode_buffer(64)
        written = self.gdi32.GetTextFaceW(self.mem_dc, 64, buffer)
        self.gdi32.SelectObject(self.mem_dc, previous)
        self.gdi32.DeleteObject(font)
        if written and buffer.value.strip():
            return buffer.value.strip()
        return None

    def _create_font(self, size: int, face: str, weight: int | None = None):  # noqa: ANN202
        """A font handle at the requested weight.

        The number is a request. The client's HUD font declares one face (OS/2
        ``usWeightClass`` 400, subfamily "Regular"), and ``tools/pc/probe-font-weight.py``
        measured what that means on the game PC: weights 100 through 500 draw
        byte-identical surfaces, so 300 is already the lightest this font can be rendered -
        not "lighter than 400" but exactly the same raster. From 700 GDI synthesises a
        heavier face. GDI still echoes the requested 300 back through ``GetObjectW``, which
        is why the readout reports what was asked for beside what came back and never
        claims the strokes weigh that much.

        The lightening that is visible on screen came from the shadow: four offsets put
        dark fringe on all four sides of every glyph, which at this size sits against every
        stem and reads as emboldening. One offset keeps it on a single side.
        """
        return self.gdi32.CreateFontW(-size, 0, 0, 0,
                                      self.font_weight if weight is None else weight,
                                      0, 0, 0, DEFAULT_CHARSET, 0, 0, 0, 0, face)

    def resolved_weight_of(self, font) -> int:  # noqa: ANN001
        """The weight GDI actually selected for this handle, or 0 if it cannot be read."""
        if not font:
            return 0
        info = _LOGFONTW()
        try:
            written = self.gdi32.GetObjectW(font, ctypes.sizeof(_LOGFONTW), ctypes.byref(info))
        except (AttributeError, OSError):
            return 0
        return int(info.lfWeight) if written else 0

    def _face_exists(self, size: int, face: str) -> bool:
        """Whether GDI really gives us this face.

        ``CreateFontW`` never fails for an unknown name; it substitutes something and
        says nothing. Asking the device context which face it ended up with is the
        only way to tell "MingLiU" from "whatever Arial is here", and that difference
        is exactly whether the zh bearing words render or come out as blank boxes.

        Any failure here means "cannot tell", which is reported as "this face is not
        available" rather than raised: a missing glyph is a cosmetic problem and must
        never stop the readout from appearing.
        """
        try:
            font = self._create_font(size, face)
            if not font:
                return False
            previous = self.gdi32.SelectObject(self.mem_dc, font)
            buffer = ctypes.create_unicode_buffer(64)
            written = self.gdi32.GetTextFaceW(self.mem_dc, 64, buffer)
            self.gdi32.SelectObject(self.mem_dc, previous)
            self.gdi32.DeleteObject(font)
        except (AttributeError, OSError):
            return False
        return bool(written) and buffer.value.strip().lower() == face.strip().lower()

    def _pick_face(self, size: int, candidates: tuple[str, ...]) -> str:
        for face in candidates:
            if self._face_exists(size, face):
                return face
        self.face_missing = True
        return candidates[-1]

    def _release_buffer(self) -> None:
        # ``font_cjk`` may be the same handle as ``font``; deleting it twice would be a
        # double free, so only distinct handles are released.
        handles = {self.font, self.font_cjk} - {0}
        for handle in handles:
            self.gdi32.DeleteObject(handle)
        if self.bitmap:
            self.gdi32.DeleteObject(self.bitmap)
        self.bitmap = 0
        self.font = 0
        self.font_cjk = 0
        if self.mem_dc:
            self.gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = 0

    @property
    def title_band(self) -> int:
        """The space held above the first row: the title, or just a top margin.

        An empty title means there is no title band at all. The readout the player sees
        is a bare list of bosses, and reserving a title-sized gap above it would leave a
        strip of nothing at the top of the window - which is visible, because the window
        is auto-sized to its content and anchored by its top edge.
        """
        return self.title_height + 3 if self._title else 2

    def height_for(self, rows: int) -> int:
        """The window height these rows need, so the content is never clipped.

        A fixed height silently dropped whatever did not fit - the diagnostic notes
        were the first thing to go, which is the worst thing to lose, because the notes
        are what tell a correct empty list apart from a broken one.
        """
        return self.title_band + rows * self.line_height + 2

    def resize(self, left: int, top: int, width: int, height: int) -> None:
        """Reposition and resize without activating, rebuilding the surface.

        The off-screen buffer is sized to the window, so a new height needs a new DIB.
        The font face is kept rather than re-probed: the probe is a per-machine answer
        and asking again on every resize would be both slow and a possible flip.
        """
        if (left, top, width, height) == (self.left, self.top, self.width, self.height):
            return
        face = self.font_face
        size = self.font_size
        prefer_ascii = self.prefer_ascii
        cjk = self.cjk_face
        self._release_buffer()
        self.left, self.top = int(left), int(top)
        self.width, self.height = int(width), int(height)
        self.user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(HWND_TOPMOST),
                                 self.left, self.top, self.width, self.height,
                                 SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self.face_missing = False
        self._create_buffer(size, face, prefer_ascii, cjk)
        self.resolved_weight = self.resolved_weight_of(self.font)
        self.present()

    def move_to(self, left: int, top: int) -> None:
        """Follow the client rectangle without resizing, activating, or stacking."""
        self.left, self.top = int(left), int(top)
        self.user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(HWND_TOPMOST),
                                 self.left, self.top, 0, 0,
                                 SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    # ------------------------------------------------------------------- drawing
    @property
    def rows_fitting(self) -> int:
        """How many rows the window height can show, so the caller can trim the plan.

        Without this the plan's ``max_rows`` could ask for more rows than fit and the
        extras would be silently dropped at draw time, which is the kind of quiet
        truncation this project keeps paying for.
        """
        available = self.height - self.title_band - 2
        return max(1, available // self.line_height)

    def set_content(self, title: str, rows: tuple[Row, ...]) -> None:
        """Remember what to draw and present it.

        An empty title draws no title and no title band: the readout is then a bare list
        of rows, which is what the in-game window shows.
        """
        self._title = title
        self._rows = tuple(rows)
        self.present()

    def present(self) -> None:
        """Redraw the remembered content into the surface and update the window."""
        if self.framed:
            self._fill(self.background)
            self._outline()
        else:
            self._clear()
        self._draw_text()
        self._opaque_glyphs()
        self._update_layered_window()

    def _clear(self) -> None:
        """Every pixel fully transparent, so only the glyphs are drawn."""
        buffer = (ctypes.c_ubyte * (self.width * self.height * 4)).from_address(self.bits)
        ctypes.memset(buffer, 0, len(buffer))

    def _fill(self, colour: tuple[int, int, int, int]) -> None:
        red, green, blue, alpha = colour
        # Premultiplied BGRA, which is what UpdateLayeredWindow with AC_SRC_ALPHA wants.
        pixel = bytes((blue * alpha // 255, green * alpha // 255, red * alpha // 255, alpha))
        row = pixel * self.width
        for y in range(self.height):
            ctypes.memmove(ctypes.c_void_p(self.bits + y * self.width * 4), row, len(row))

    def _put(self, x: int, y: int, colour: tuple[int, int, int], alpha: int = 255) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        red, green, blue = colour
        offset = (y * self.width + x) * 4
        buffer = (ctypes.c_ubyte * 4).from_address(self.bits + offset)
        buffer[0] = blue * alpha // 255
        buffer[1] = green * alpha // 255
        buffer[2] = red * alpha // 255
        buffer[3] = alpha

    def _outline(self) -> None:
        """A one-pixel border and a title underline, so the readout reads as a HUD panel."""
        for x in range(self.width):
            self._put(x, 0, self.border, 170)
            self._put(x, self.height - 1, self.border, 170)
        for y in range(self.height):
            self._put(0, y, self.border, 170)
            self._put(self.width - 1, y, self.border, 170)
        if not self._title:
            # Nothing to underline, and the rule would land on the top border.
            return
        for x in range(3, self.width - 3):
            self._put(x, self.title_height - 2, self.title_colour, 150)

    def _draw_text(self) -> None:
        self.gdi32.SelectObject(self.mem_dc, self.font)
        flags = ALIGN_FLAGS[self.align] | DT_SINGLELINE | DT_NOPREFIX | DT_END_ELLIPSIS
        if self._title:
            self._text(self._title, 8, 2, self.width - 8, self.title_height,
                       self.title_colour, flags)
        y = self.title_band
        for row in self._rows:
            if y + self.line_height > self.height - 2:
                break
            self._text(row.text, 8, y, self.width - 8, y + self.line_height, row.colour, flags)
            y += self.line_height
        # Remembered so the alpha pass only walks the rows that can hold glyphs.
        self.last_text_y = y

    def _opaque_glyphs(self) -> None:
        """Give every pixel we drew a full alpha.

        GDI draws text into a 32-bit DIB *without touching the alpha byte*. On an
        opaque surface that is harmless - the backing already left 255 there - but on a
        cleared surface, where every pixel is ``alpha 0``, the glyphs would be drawn and
        then be invisible, because ``UpdateLayeredWindow`` composites by alpha.

        The test is exact rather than a guess: the surface was cleared to zero and the
        only thing drawn on it is the text, so a pixel with any non-zero colour channel
        is ours. Only the rows the text reached are scanned, which keeps a frame cheap.
        """
        if self.framed:
            return          # the backing already put 255 in the alpha byte
        for y in range(max(0, self.title_band - 2), self.last_text_y + 1):
            base = y * self.width * 4
            row = (ctypes.c_ubyte * (self.width * 4)).from_address(self.bits + base)
            for x in range(self.width):
                offset = x * 4
                if row[offset] or row[offset + 1] or row[offset + 2]:
                    row[offset + 3] = 255

    def _text(self, text: str, left: int, top: int, right: int, bottom: int,
              colour: tuple[int, int, int], flags: int) -> None:
        """Draw a line, with a dark drop shadow first when there is no backing.

        GDI cannot outline a glyph, so the shadow is the text drawn once in near-black
        offset by one pixel and then in its own colour on top. Without it, green text
        with a fully transparent backing disappears over bright terrain - which is the
        one thing that would make the transparent mode unusable.

        One pixel, and one offset. Four offsets were measured to add 141 pixels of dark
        fringe (6% more ink at weight 300) on every side of every glyph, which at 10 px
        presses against every stem and is what a heavier weight looks like.
        """
        if self.text_shadow and not self.framed:
            # One offset, not four, so the fringe stays on a single side of each glyph
            # instead of pressing against every stem. A single drop shadow to the lower
            # right is still enough to hold the glyphs against a bright background and
            # leaves the apparent weight to the font, which at this size has no lighter
            # face to offer (see _create_font).
            self.gdi32.SetTextColor(self.mem_dc, _rgb(SHADOW_COLOUR))
            self.user32.DrawTextW(self.mem_dc, text, -1,
                                  ctypes.byref(wintypes.RECT(left + 1, top + 1,
                                                             right + 1, bottom + 1)), flags)
        # The client's HUD face has no CJK glyphs, so a row with Chinese in it is drawn
        # in the face that does. Without this the header and the notes are a row of
        # empty boxes next to boss lines that look perfect.
        self.gdi32.SelectObject(self.mem_dc, self.font_cjk if needs_cjk(text) else self.font)
        self.gdi32.SetTextColor(self.mem_dc, _rgb(colour))
        self.user32.DrawTextW(self.mem_dc, text, -1,
                              ctypes.byref(wintypes.RECT(left, top, right, bottom)), flags)

    def _update_layered_window(self) -> None:
        size = wintypes.SIZE(self.width, self.height)
        source = wintypes.POINT(0, 0)
        destination = wintypes.POINT(self.left, self.top)
        ok = self.user32.UpdateLayeredWindow(self.hwnd, self.screen_dc,
                                             ctypes.byref(destination), ctypes.byref(size),
                                             self.mem_dc, ctypes.byref(source), 0,
                                             ctypes.byref(self.blend), ULW_ALPHA)
        if not ok:
            raise OSError(f"UpdateLayeredWindow failed: {ctypes.get_last_error()}")

    # ------------------------------------------------------------------ teardown
    def describe(self) -> str:
        """Whether the window is on screen and where, read back from Windows.

        The position is read back rather than assumed because a scaled display means
        the coordinates this process placed the window at and the physical pixels
        are not the same numbers.
        """
        rect = wintypes.RECT()
        visible = bool(self.user32.IsWindowVisible(wintypes.HWND(self.hwnd)))
        placed = bool(self.user32.GetWindowRect(wintypes.HWND(self.hwnd), ctypes.byref(rect)))
        where = (f"({rect.left},{rect.top})-({rect.right},{rect.bottom})" if placed else "unreadable")
        font = f"; font={self.font_face}" + (" (no CJK face found)" if self.face_missing else "")
        backing = (f"opaque alpha={self.background[3]}" if self.framed
                   else "transparent backing (text only)")
        shadow = "; text shadow on" if (self.text_shadow and not self.framed) else ""
        cjk = f", CJK {self.cjk_face}" if self.cjk_face != self.font_face else ""
        # GDI echoes the requested weight back on this machine even when the family has
        # a single face, so this line records what was asked for and what came back -
        # it is deliberately not phrased as a claim about the drawn strokes.
        weight = (f"; weight={self.resolved_weight} (asked {self.font_weight})"
                  if self.resolved_weight else "")
        return (f"overlay visible={visible} at {where}{font}{cjk}{weight}; align={self.align}; "
                f"{backing}{shadow}")

    def dump(self, path: str, backdrop: tuple[int, int, int] = (96, 96, 96)) -> str:
        """Write the surface the overlay is presenting, as a 24-bit BMP.

        A layered window is not reproduced by a screen capture on every display
        configuration, so "what is the overlay drawing" cannot be answered by
        photographing the desktop. This writes the same pixels the window receives.

        BMP has no alpha channel, so the surface is composited over ``backdrop``
        (mid-grey by default). With a transparent backing the glyphs would otherwise
        be drawn on pure black and the whole surface would look like an opaque black
        rectangle, which is the opposite of what is being presented. The window's own
        ``background alpha`` is reported by :meth:`describe`, and the screenshot over
        the game is what actually shows the transparency.
        """
        raw = ctypes.string_at(self.bits, self.width * self.height * 4)
        pixels = composite_bmp_rows(raw, self.width, self.height, backdrop)
        header = struct.pack("<2sIHHI", b"BM", 14 + 40 + len(pixels), 0, 0, 14 + 40)
        info = struct.pack("<IiiHHIIiiII", 40, self.width, self.height, 1, 24, 0,
                           len(pixels), 2835, 2835, 0, 0)
        with open(path, "wb") as handle:
            handle.write(header + info + pixels)
        return path

    def close(self) -> None:
        self._release_buffer()
        if getattr(self, "screen_dc", None):
            self.user32.ReleaseDC(None, self.screen_dc)
            self.screen_dc = 0
        if self.hwnd:
            self.user32.DestroyWindow(wintypes.HWND(self.hwnd))
            self.hwnd = 0
        # The class outlives the window, so it is released too. The name is unique to this
        # instance (see _class_name), which is what makes this the owner's call and no one
        # else's; a name derived from the object's address instead collided, and the
        # unlucky second overlay failed to open with an opaque
        # "RegisterClassW failed: 1410".
        if self._class_name:
            self.user32.UnregisterClassW(self._class_name, None)


def anchored_overlay(
    anchor: str,
    area_left: int,
    area_top: int,
    area_width: int,
    area_height: int,
    width: int,
    height: int,
    offset_x: int = 0,
    offset_y: int = 0,
    **kwargs,  # noqa: ANN003 - forwarded to Overlay
) -> Overlay:
    """Build an overlay placed by an anchor, so the caller never computes a corner."""
    left, top = place(anchor, area_left, area_top, area_width, area_height,
                      width, height, offset_x, offset_y)
    return Overlay(left, top, width, height, **kwargs)
