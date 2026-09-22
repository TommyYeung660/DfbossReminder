"""Where the game's client area is on screen, so an overlay can sit on it.

The fourth requirement asks for an overlay *inside* the game's interface, like the
buff row the client already draws. That needs one thing from the outside world:
the game window's client rectangle in screen coordinates, so the overlay can be
placed over it and follow it if the window moves.

Read-only by construction: the window is found by its class and title, its client
rectangle is measured, and its process id is read. No input is sent, nothing is
written, and no window is activated - ``GetClientRect`` and ``ClientToScreen`` do
not require the window to be focused.

Exclusive fullscreen is reported as unsupported rather than worked around: a
topmost window cannot be drawn over a fullscreen swap chain, and pretending
otherwise would produce an overlay the player cannot see. Windowed and
borderless-windowed are supported.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

DEFAULT_EXE = "DeadFrontier.exe"
DEFAULT_TITLE = "Dead Frontier"
UNITY_WINDOW_CLASS = "UnityWndClass"


@dataclass(frozen=True)
class Rect:
    """A rectangle in screen coordinates, origin top-left."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def as_dict(self) -> dict:
        return {"left": self.left, "top": self.top, "width": self.width, "height": self.height}


@dataclass(frozen=True)
class GameWindow:
    """The running client, measured. ``client`` is in screen coordinates."""

    hwnd: int
    pid: int
    title: str
    client: Rect
    screen: Rect
    exclusive_fullscreen: bool

    @property
    def presentation_note(self) -> str:
        if self.exclusive_fullscreen:
            return "exclusive fullscreen: an overlay cannot be drawn on it"
        return f"client {self.client.width}x{self.client.height} at " \
               f"({self.client.left}, {self.client.top})"


def _bind():  # noqa: ANN202 - ctypes handles
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    return user32


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_image_path(pid: int) -> Path | None:
    """The executable a process is running from, or ``None``.

    Read-only and cheap: the query right is enough to ask for the image path, and the
    process is closed again immediately. This is how the client's install directory is
    found, so the tool can take the HUD font from the same installation it is already
    reading rather than from a path written down somewhere.
    """
    if sys.platform != "win32" or pid <= 0:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                    wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value) if buffer.value else None
    finally:
        kernel32.CloseHandle(handle)


def game_data_dir(window: GameWindow | None = None, exe: str = DEFAULT_EXE) -> Path | None:
    """The client's ``*_Data`` directory, where its assets (and its font) live."""
    window = window if window is not None else find_game_window(exe=exe)
    if window is None:
        return None
    image = process_image_path(window.pid)
    if image is None:
        return None
    for candidate in (image.parent / f"{image.stem}_Data", image.parent / "Data"):
        if candidate.is_dir():
            return candidate
    return None


def screen_rect(user32=None) -> Rect | None:  # noqa: ANN001
    """The primary monitor's size in physical pixels."""
    if sys.platform != "win32":
        return None
    user32 = user32 or _bind()
    return Rect(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def find_game_window(
    exe: str = DEFAULT_EXE,
    title: str = DEFAULT_TITLE,
) -> GameWindow | None:
    """The client's window and its client rectangle, or ``None`` when it is absent.

    The lookup tries the Unity window class first and the title second, which is
    how the sibling tool has found this client reliably: a window titled
    "Dead Frontier" owned by another process is possible in principle, but the
    Unity class plus the title together are specific enough in practice.
    """
    if sys.platform != "win32":
        return None
    user32 = _bind()
    hwnd = user32.FindWindowW(UNITY_WINDOW_CLASS, title) or user32.FindWindowW(None, title)
    if not hwnd:
        return None
    return measure_window(user32, int(hwnd))


def measure_window(user32, hwnd: int, screen: Rect | None = None) -> GameWindow | None:  # noqa: ANN001
    """Measure an already-known window.

    ``screen`` is passed in so the fullscreen test can be exercised without a
    monitor: the only thing the test needs is a rectangle to compare against.
    """
    client = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
        return None
    origin = wintypes.POINT(client.left, client.top)
    if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
        return None
    width = int(client.right - client.left)
    height = int(client.bottom - client.top)
    if width <= 0 or height <= 0:
        return None

    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, 256)

    screen = screen or screen_rect(user32) or Rect(0, 0, width, height)
    # A client area that covers the whole monitor is *either* a fullscreen swap
    # chain or a borderless window sized to the monitor; the two cannot be told
    # apart from the client rectangle alone. It is therefore reported as a warning
    # and not used to refuse to draw, because a borderless window at monitor size is
    # a presentation this project does support and guessing wrong would disable the
    # overlay for a player who did nothing unusual.
    covers_screen = width >= screen.width and height >= screen.height
    return GameWindow(
        hwnd=hwnd,
        pid=int(pid.value),
        title=buffer.value,
        client=Rect(int(origin.x), int(origin.y), width, height),
        screen=screen,
        exclusive_fullscreen=bool(covers_screen),
    )
