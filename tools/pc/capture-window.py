"""Photograph a window by title, without activating it.

The settings window is the one part of this project that has to be looked at: its labels
are Chinese, and "the strings in the source are Chinese" says nothing about whether
Windows draws them or puts up a row of boxes. A screenshot is the only honest check.

It cannot be an ordinary screen capture. Cropping the screen's rectangle would need the
window to be on top, and bringing it to the front takes the focus away from whatever the
player is doing - mid-fight, that is worse than not having the picture. ``PrintWindow``
asks the window to draw itself into a device context instead: no activation, no focus
change, nothing moved. It renders the whole window, frame included, which is exactly what
a dialog's evidence should show.

Usage (game PC, inside the interactive session):
    py -3 tools\\pc\\capture-window.py --title "DFBossReminder" --label config-gui
    py -3 tools\\pc\\capture-window.py --title "DFBossReminder" --list
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# PrintWindow's flags. PW_CLIENTONLY asks for the client area alone; the render-full-content
# flag is needed by windows that draw themselves with a surface (a layered or DirectX
# window comes out blank without it), so it is tried first and the plain request is the
# fallback.
PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENTONLY = 0x00000001
DIB_RGB_COLORS = 0
BI_RGB = 0


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", wintypes.DWORD * 3)]


def bind():  # noqa: ANN202 - ctypes handles
    """Bind every call with its real argument and return types.

    ctypes assumes ``c_int`` for anything it is not told about, and a handle that comes
    back as a 32-bit int is a truncated handle on 64-bit Windows - the DC is then invalid
    and every later call fails with a code that says nothing about the cause. A test in
    this project's suite reads these lines and fails if a call is bound on the wrong
    library or not bound at all.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), wintypes.UINT]
    gdi32.GetDIBits.restype = ctypes.c_int
    return user32, gdi32


def find_windows(user32) -> list[tuple[int, str, tuple[int, int, int, int]]]:
    """Every window whose title contains the needle, as (hwnd, title, rectangle).

    A window that is not visible is skipped: the point is to photograph what a person
    would see, and an invisible window would render as a blank image that proves nothing.
    """
    found: list[tuple[int, str, tuple[int, int, int, int]]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):  # noqa: ANN001, ANN202
        if not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        length = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
        rect = wintypes.RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return True
        title = buffer.value
        if _needle.lower() in title.lower():
            found.append((int(hwnd), title,
                          (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)))
        return True

    user32.EnumWindows(visit, 0)
    return found


_needle = ""


def shoot(user32, gdi32, hwnd: int, width: int, height: int, flag: int) -> bytes | None:
    """The window's own pixels as a 24-bit BMP, or None when it will not render.

    Any of the GDI calls here can fail - a window can be mid-teardown, or refuse to draw
    itself - and every one of them is reported rather than assumed, because a blank image
    that "succeeded" is the worst evidence there is.
    """
    window_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
    if not window_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not memory_dc or not bitmap:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)
        return None
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(wintypes.HWND(hwnd), memory_dc, flag):
            return None
        header = _BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.bmiHeader.biWidth = width
        header.bmiHeader.biHeight = -height            # top-down
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = BI_RGB
        stride = width * 4
        buffer = (ctypes.c_ubyte * (stride * height))()
        if not gdi32.GetDIBits(memory_dc, bitmap, 0, height, ctypes.byref(buffer),
                               ctypes.byref(header), DIB_RGB_COLORS):
            return None
        return to_bmp(bytes(buffer), width, height)
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)


def to_bmp(pixels: bytes, width: int, height: int) -> bytes:
    """32-bit BGRA rows re-packed as a 24-bit BMP.

    Pure arithmetic on bytes, so the packing can be checked on a machine that has no GDI
    at all - which is the half of this tool that is testable.
    """
    import struct

    stride = width * 4
    rows = []
    for y in range(height):
        row = pixels[y * stride:(y + 1) * stride]
        # Bottom-up for the file format, and BGR with the padding a BMP row needs.
        rows.append(b"".join(row[x + 0:x + 3] for x in range(0, stride, 4)))
    padding = (-(width * 3)) % 4
    body = b""
    for row in reversed(rows):
        body += row + b"\x00" * padding
    header = struct.pack("<2sIHHI", b"BM", 14 + 40 + len(body), 0, 0, 14 + 40)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, BI_RGB, len(body),
                       2835, 2835, 0, 0)
    return header + info + body


def main() -> int:
    global _needle
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="substring of the window title")
    parser.add_argument("--label", default="", help="name for the file, default from the title")
    parser.add_argument("--out-dir", default="", help="where to write it")
    parser.add_argument("--list", action="store_true", help="only list the matches")
    parser.add_argument("--wait", type=float, default=0.0,
                        help="seconds to keep looking for the window to appear")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("this tool only runs on Windows", file=sys.stderr)
        return 1

    # The window titles this prints are Chinese. Writing to a pipe makes Python use the
    # locale's code page, and the caller then decodes the bytes with the same guess - which
    # is what turned a window title into "cp950 codec can't decode byte 0xae" inside the
    # probe's reader thread. Both sides are pinned to UTF-8 instead: this one here, and
    # the caller's decoding.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):        # pragma: no cover - a redirected stream
            pass

    user32, gdi32 = bind()
    _needle = args.title

    deadline = time.time() + max(0.0, args.wait)
    matches = find_windows(user32)
    while not matches and time.time() < deadline:
        time.sleep(0.5)
        matches = find_windows(user32)

    if not matches:
        print(f"no visible window matches {args.title!r}")
        return 1
    for hwnd, title, (left, top, width, height) in matches:
        print(f"matched hwnd={hex(hwnd)} {width}x{height} at ({left},{top}) {title!r}")
    if args.list:
        return 0

    hwnd, title, (left, top, width, height) = matches[0]
    image = None
    for flag, name in ((PW_RENDERFULLCONTENT, "render-full-content"),
                       (PW_CLIENTONLY, "client-only"),
                       (0, "default")):
        image = shoot(user32, gdi32, hwnd, width, height, flag)
        if image:
            print(f"PrintWindow rendered with {name}")
            break
        print(f"PrintWindow returned nothing with {name}, trying the next")
    if not image:
        print("PROBLEM: the window would not render itself, so there is no picture")
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else (
        PROJECT_ROOT / "tools" / "pc" / "evidence")
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or args.title
    safe = "".join(character if character.isalnum() or character in "-_" else "-"
                   for character in label)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    target = out_dir / f"{stamp}-window-{safe}.bmp"
    target.write_bytes(image)
    print(f"wrote {target} ({width}x{height}, {len(image)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
