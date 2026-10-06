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
    """One line of the readout: its text, its colour, and what a tick would hide.

    ``key`` is the spawn the row belongs to, and only boss rows have one: a tick on a note
    or a waypoint would have nothing to hide. It is what the box column hands back when the
    player clicks, so nothing here has to know what a boss event is.
    """

    text: str
    colour: tuple[int, int, int] = (235, 235, 235)
    key: tuple[str, float] | None = None


# The tick box beside each row. Its size follows the font size for the same reason the line
# height does - the box has to look like it belongs to the row it sits next to - and the
# column is the box plus a margin on each side so the border is never on the window edge.
CHECK_PAD = 2
CHECK_TEXT_GAP = 5
# The box's own colours: a faint dark fill so the box reads as a control rather than as a
# hole in the text, and enough alpha that the whole box is hit-testable (see CheckColumn).
BOX_FILL = (18, 18, 18)
BOX_FILL_ALPHA = 96
# The rest of the row cell: not a pixel anybody can see, but a pixel the mouse can hit, which
# is what makes the whole row a target instead of an eleven-pixel square.
CELL_ALPHA = 6


def check_size(font_size: int) -> int:
    """The box's side, in pixels: as tall as the font, within reason."""
    return max(8, min(16, int(font_size)))


def check_column_width(font_size: int) -> int:
    """The width of the window that holds the boxes."""
    return check_size(font_size) + 2 * CHECK_PAD


def check_gutter(font_size: int) -> int:
    """What the readout's text gives up at its right edge for that window."""
    return check_column_width(font_size) + CHECK_TEXT_GAP


@dataclass(frozen=True)
class Box:
    """One tick box: what it hides, where it is, and the colour of its row.

    The rectangle is in the box column's own client coordinates, so hit-testing a click is
    comparing two numbers - which is why it can be tested without Windows.
    """

    key: tuple[str, float]
    rect: tuple[int, int, int, int]          # left, top, right, bottom
    colour: tuple[int, int, int] = (235, 235, 235)

    def contains(self, x: int, y: int) -> bool:
        left, top, right, bottom = self.rect
        return left <= x < right and top <= y < bottom


def boxes_for(rows: tuple[Row, ...], title_band: int, line_height: int,
              font_size: int) -> tuple[Box, ...]:
    """The boxes for these rows, one per row that has something to hide.

    Every row advances the cursor, including the rows with no key: the boxes have to line up
    with the rows the readout drew, and a note between two bosses must leave the gap it
    occupies rather than pulling the boxes up.
    """
    size = check_size(font_size)
    top_offset = max(0, (line_height - size) // 2)
    boxes: list[Box] = []
    for index, row in enumerate(rows):
        if row.key is None:
            continue
        top = title_band + index * line_height + top_offset
        boxes.append(Box(key=row.key,
                         rect=(CHECK_PAD, top, CHECK_PAD + size, top + size),
                         colour=row.colour))
    return tuple(boxes)


def box_at(x: int, y: int, boxes: tuple[Box, ...]) -> Box | None:
    """The box under a point, or ``None`` - the whole of the click routing."""
    for box in boxes:
        if box.contains(x, y):
            return box
    return None


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
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
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


# ------------------------------------------------------------------- messages
#
# A window that is meant to be clicked needs someone to take its messages off the queue:
# nothing arrives in a window procedure until the thread that owns the window pumps. The
# readout did not need one until it grew a tick box - and that is also why a window call
# from *another* thread used to hang for ever: nothing here ever dispatched anything.
PM_REMOVE = 0x0001
WM_NCHITTEST = 0x0084
WM_MOUSEACTIVATE = 0x0021
WM_LBUTTONDOWN = 0x0201
HTCLIENT = 1
HTTRANSPARENT = -1
MA_NOACTIVATE = 3

_PUMP = None


def _pump_api():  # noqa: ANN202 - ctypes handles
    """user32's queue calls, bound once, and only on Windows."""
    global _PUMP  # noqa: PLW0603 - one process-wide binding, like ``_bind``
    if _PUMP is not None:
        return _PUMP
    if sys.platform != "win32":
        raise RuntimeError("the overlay needs Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_long
    _PUMP = user32
    return _PUMP


def pump_messages(limit: int = 256) -> int:
    """Dispatch what Windows queued for this thread, and say how many messages it was.

    Pumped rather than left to Windows because our thread owns the windows: the boxes only
    work if somebody dispatches their clicks, and the count is returned so a caller can say
    what happened in a log rather than guessing.
    """
    user32 = _pump_api()
    message = wintypes.MSG()
    count = 0
    while count < limit and user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
        count += 1
    return count


def _click_point(lparam: int) -> tuple[int, int]:
    """The client coordinates in a mouse message's ``lparam``.

    Signed on purpose: a window can be dragged to a negative coordinate, and reading these
    as unsigned puts a click on the left edge 65 000 pixels away.
    """
    return (ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value)


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
        check_gutter: int = 0,
    ) -> None:
        self.user32, self.gdi32 = _bind()
        self.width, self.height = int(width), int(height)
        self.left, self.top = int(left), int(top)
        self.background = background
        self.border = border
        self.title_colour = title_colour
        self.text_shadow = text_shadow
        self.align = align if align in ALIGN_FLAGS else "right"
        # Space kept at the right edge for the tick boxes, which live in a window of their
        # own (see CheckColumn). The rows are drawn inside it, so a long line is elided by
        # the drawing rectangle instead of running under the boxes.
        self.check_gutter = max(0, int(check_gutter))
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
            self._text(row.text, 8, y, self.width - 8 - self.check_gutter,
                       y + self.line_height, row.colour, flags)
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
        boxes = f"; {self.check_gutter}px reserved for the tick boxes" if self.check_gutter else ""
        return (f"overlay visible={visible} at {where}{font}{cjk}{weight}; align={self.align}; "
                f"{backing}{shadow}{boxes}")

    @property
    def rows(self) -> tuple[Row, ...]:
        """What is on screen, for a test or a probe to read back."""
        return self._rows

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


class CheckColumn:
    """The narrow window that holds the tick boxes: the part that is meant to be clicked.

    It is a window of its own rather than pixels inside the readout, and the reason is the
    one safety property this project has spent the most effort on. The readout is created
    with ``WS_EX_TRANSPARENT``, which Windows honours by skipping the window *entirely* when
    it hit-tests the mouse - that is what makes "a click over the readout reaches the game"
    provable rather than hopeful, and it is worth keeping on the window the player stares at
    for an hour at a time. A window with that flag can never receive a click, so the part
    that must receive one cannot live in it.

    What keeps *this* window out of the way is the other documented rule: hit-testing a
    layered window follows its pixels, and a pixel whose alpha is zero lets the mouse
    through. So the surface is cleared to nothing and only the boxes are drawn, and every
    click that is not on a box goes to the game underneath - which is also why the boxes are
    filled rather than drawn as outlines: an outline would leave the middle of the box
    transparent, and a click there would fall through to the game.

    The strip is narrow (the width of one box plus its margins) on purpose. Even in the
    worst case, where the alpha rule did not apply at all, what it could block is a column
    the width of a checkbox - not the readout.
    """

    kind = "checkboxes"

    def __init__(
        self,
        left: int,
        top: int,
        width: int,
        height: int,
        font_size: int = 14,
        log=print,  # noqa: ANN001
    ) -> None:
        self.user32, self.gdi32 = _bind()
        self.left, self.top = int(left), int(top)
        self.width, self.height = int(width), int(height)
        self.font_size = int(font_size)
        self.log = log
        # Set before the window exists, because messages arrive *during* CreateWindowExW:
        # Windows sends WM_NCCREATE and WM_NCCALCSIZE before it returns a handle, so
        # anything in the window procedure that reaches for self.hwnd must find something
        # there. The first live run of this window died exactly that way - the window
        # procedure raised, WM_NCCREATE answered 0, and CreateWindowExW failed with no error
        # number at all, which read like a resource problem rather than an ordering one.
        self.hwnd = 0
        self.boxes: tuple[Box, ...] = ()
        self.errors: list[str] = []
        # Set by the presenter: called with the key of the box that was clicked, on this
        # window's own thread (see pump_messages).
        self.on_check = None                            # noqa: ANN001 - Callable[[key], None]
        self._class_name = f"DFBossReminderCheck{os.getpid()}_{next(_CLASS_SEQ)}"

        self._register_class()
        # No WS_EX_TRANSPARENT: this window exists to be clicked. Everything else is the
        # same set the readout uses, and for the same reasons - layered for per-pixel alpha,
        # topmost so it stays over the client, toolwindow so it is not in alt-tab, and
        # noactivate so a click can never take focus from the game.
        self.hwnd = self.user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            self._class_name, "DFBossReminderBoxes", WS_POPUP,
            self.left, self.top, self.width, self.height, None, None, None, None)
        if not self.hwnd:
            raise OSError(f"CreateWindowExW failed for the box column: "
                          f"{ctypes.get_last_error()}")
        self._create_buffer()
        self.user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self.present()

    # -------------------------------------------------------------------- window
    def _register_class(self) -> None:
        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        def _proc(hwnd, message, wparam, lparam):  # noqa: ANN001, ANN202
            try:
                return self._handle(hwnd, message, wparam, lparam)
            except Exception as error:              # noqa: BLE001 - never kill the pump
                # This runs inside DispatchMessage, on the loop's thread: an exception here
                # would come out of the pump and take the whole readout down. A broken
                # click handler must cost a click, not the overlay.
                self._note(f"the box column failed on message {message:#06x}: {error}")
                return 0

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
            raise OSError(f"RegisterClassW failed for the box column: "
                          f"{ctypes.get_last_error()}")

    def _note(self, message: str) -> None:
        self.errors.append(message)
        del self.errors[:-8]                            # keep the last few, not the session
        self.log(message)

    def _to_client(self, x: int, y: int) -> tuple[int, int]:
        """A screen point as this window's client point.

        Needed because ``WM_NCHITTEST`` carries **screen** coordinates while every mouse
        message that follows carries client ones, and comparing the wrong pair is invisible:
        the hit test simply answers "not mine", the system routes the click to the window
        underneath, and the box never hears about it. ``WindowFromPoint`` does not ask a
        window at all, so nothing about it notices either - which is exactly how this shipped
        once with a passing test.
        """
        if not self.hwnd:
            return x, y
        point = wintypes.POINT(int(x), int(y))
        if self.user32.ScreenToClient(wintypes.HWND(self.hwnd), ctypes.byref(point)):
            return int(point.x), int(point.y)
        return x - self.left, y - self.top

    def _handle(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:  # noqa: ARG002
        """What this window does with a message, which is very little on purpose.

        ``hwnd`` is the one Windows passed, and it is used rather than ``self.hwnd``: the
        first messages of a window's life arrive before ``CreateWindowExW`` has returned, so
        ``self.hwnd`` is still zero at that point.
        """
        if message == WM_NCHITTEST:
            # Screen coordinates in, client coordinates out (see _to_client).
            x, y = self._to_client(*_click_point(lparam))
            # Belt and braces: the alpha rule already hides the empty pixels from
            # hit-testing, so this is only reached on a box - but if it is ever reached
            # elsewhere, the click must still go through to the game.
            return HTCLIENT if box_at(x, y, self.cells()) else HTTRANSPARENT
        if message == WM_MOUSEACTIVATE:
            # A click must not activate this window, or the game would lose the keyboard.
            return MA_NOACTIVATE
        if message == WM_LBUTTONDOWN:
            # Client coordinates here, unlike WM_NCHITTEST above.
            x, y = _click_point(lparam)
            box = box_at(x, y, self.cells())
            if box is not None and self.on_check is not None:
                # On the button *down*: the row goes as soon as the player clicks, and the
                # release that follows lands on boxes that have moved up under the cursor -
                # acting on it as well would hide a second boss nobody aimed at.
                self.on_check(box.key)
            return 0
        return self.user32.DefWindowProcW(wintypes.HWND(hwnd), message, wparam, lparam)

    def _create_buffer(self) -> None:
        self.screen_dc = self.user32.GetDC(None)
        self.mem_dc = self.gdi32.CreateCompatibleDC(self.screen_dc)
        header = _BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.bmiHeader.biWidth = self.width
        header.bmiHeader.biHeight = -self.height           # top-down
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = BI_RGB
        bits = ctypes.c_void_p()
        self.bitmap = self.gdi32.CreateDIBSection(self.mem_dc, ctypes.byref(header),
                                                  DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        self.bits = bits.value
        if not self.bitmap or not self.bits:
            raise OSError("could not create the box column's DIB section")
        self.gdi32.SelectObject(self.mem_dc, self.bitmap)
        self.blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    def _release_buffer(self) -> None:
        if self.bitmap:
            self.gdi32.DeleteObject(self.bitmap)
            self.bitmap = 0
        if self.mem_dc:
            self.gdi32.DeleteDC(self.mem_dc)
            self.mem_dc = 0

    # ------------------------------------------------------------------- content
    def set_boxes(self, rows: tuple[Row, ...], title_band: int, line_height: int) -> None:
        """Work out the boxes for the rows the readout just drew, and present them.

        Called by the presenter with the *same* rows it handed the readout, so a box can
        never point at a row that is not there.
        """
        self.boxes = boxes_for(rows, title_band, line_height, self.font_size)
        self.line_height = int(line_height)
        self.present()

    def cells(self) -> tuple[Box, ...]:
        """The boxes, grown to the full row cell, for the hit test and the fill.

        A box is eleven pixels square and the readout is read at a glance, so aiming at the
        exact square is a test of the player's aim rather than of their intent: a click a
        pixel high, low or to the side is a click they meant. The cell is one row tall and as
        wide as the column, and the part of it outside the box is drawn at an alpha nobody
        can see - which is all the hit test needs, since a layered window's transparent
        pixels are the pixels that let the mouse through.
        """
        grown: list[Box] = []
        for box in self.boxes:
            left, top, right, bottom = box.rect
            row_top = top - (self.line_height - (bottom - top)) // 2
            grown.append(Box(box.key, (0, row_top, self.width, row_top + self.line_height),
                             box.colour))
        return tuple(grown)

    def present(self) -> None:
        """Clear to nothing, then draw the boxes - the only opaque pixels in this window."""
        buffer = (ctypes.c_ubyte * (self.width * self.height * 4)).from_address(self.bits)
        ctypes.memset(buffer, 0, len(buffer))
        # The invisible part first: the whole cell is a target, so it has to be a pixel with
        # a non-zero alpha, and at alpha 6 it is not a pixel anyone can see.
        for cell in self.cells():
            self._fill_rect(cell.rect, (18, 18, 18), CELL_ALPHA)
        for box in self.boxes:
            self._draw_box(box)
        self._update_layered_window()

    def _fill_rect(self, rect: tuple[int, int, int, int], colour: tuple[int, int, int],
                   alpha: int) -> None:
        left, top, right, bottom = rect
        for y in range(max(0, top), min(self.height, bottom)):
            for x in range(max(0, left), min(self.width, right)):
                self._put(x, y, colour, alpha)

    def _draw_box(self, box: Box) -> None:
        """A dark fill with the row's own colour as its border, so a box says which row.

        The fill is what makes the whole box clickable: a transparent middle would let a
        click fall through to the game, and a box you have to hit the frame of is a box that
        does not work. It is drawn faintly - the readout is a transparent HUD, and a row of
        solid chips would be more ink than the text beside them.
        """
        left, top, right, bottom = box.rect
        for y in range(top, bottom):
            for x in range(left, right):
                edge = x in (left, right - 1) or y in (top, bottom - 1)
                self._put(x, y, box.colour if edge else BOX_FILL,
                          235 if edge else BOX_FILL_ALPHA)

    def _put(self, x: int, y: int, colour: tuple[int, int, int], alpha: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        red, green, blue = colour
        offset = (y * self.width + x) * 4
        buffer = (ctypes.c_ubyte * 4).from_address(self.bits + offset)
        buffer[0] = blue * alpha // 255
        buffer[1] = green * alpha // 255
        buffer[2] = red * alpha // 255
        buffer[3] = alpha

    def _update_layered_window(self) -> None:
        size = wintypes.SIZE(self.width, self.height)
        source = wintypes.POINT(0, 0)
        destination = wintypes.POINT(self.left, self.top)
        ok = self.user32.UpdateLayeredWindow(self.hwnd, self.screen_dc,
                                             ctypes.byref(destination), ctypes.byref(size),
                                             self.mem_dc, ctypes.byref(source), 0,
                                             ctypes.byref(self.blend), ULW_ALPHA)
        if not ok:
            raise OSError(f"UpdateLayeredWindow failed for the box column: "
                          f"{ctypes.get_last_error()}")

    # ------------------------------------------------------------------ movement
    def place(self, left: int, top: int, width: int, height: int) -> None:
        """Follow the readout. Any change to the surface needs a new DIB."""
        if (left, top, width, height) == (self.left, self.top, self.width, self.height):
            return
        self._release_buffer()
        self.left, self.top = int(left), int(top)
        self.width, self.height = int(width), int(height)
        self.user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(HWND_TOPMOST),
                                 self.left, self.top, self.width, self.height,
                                 SWP_NOACTIVATE | SWP_SHOWWINDOW)
        self._create_buffer()
        self.present()

    def move_to(self, left: int, top: int) -> None:
        if (left, top) == (self.left, self.top):
            return
        self.left, self.top = int(left), int(top)
        self.user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(HWND_TOPMOST),
                                 self.left, self.top, 0, 0,
                                 SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

    # ------------------------------------------------------------------ reporting
    def describe(self) -> str:
        rect = wintypes.RECT()
        visible = bool(self.user32.IsWindowVisible(wintypes.HWND(self.hwnd)))
        placed = bool(self.user32.GetWindowRect(wintypes.HWND(self.hwnd), ctypes.byref(rect)))
        where = (f"({rect.left},{rect.top})-({rect.right},{rect.bottom})"
                 if placed else "unreadable")
        broken = f"; {len(self.errors)} failed message(s)" if self.errors else ""
        return (f"boxes visible={visible} at {where}, {len(self.boxes)} box(es), "
                f"click-through except on a box{broken}")

    def dump(self, path: str, backdrop: tuple[int, int, int] = (96, 96, 96)) -> str:
        """The column's own surface as a BMP, for evidence about what is clickable."""
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
