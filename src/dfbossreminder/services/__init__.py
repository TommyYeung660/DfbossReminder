"""The two outside worlds: the dfprofiler API and the game window's rectangle.

Both take their side effect by injection, so the tests run on any OS with no
network and no Windows: the profiler client accepts a ``transport`` callable, and
the window locator is a thin wrapper over ctypes that is only reached on Windows.
"""

from __future__ import annotations

from .profiler import (
    ProfilerClient,
    ProfilerError,
    account_name,
    fetch_state,
    player_block,
)
from .window import GameWindow, Rect, find_game_window, measure_window, screen_rect

__all__ = [
    "GameWindow",
    "ProfilerClient",
    "ProfilerError",
    "Rect",
    "account_name",
    "fetch_state",
    "find_game_window",
    "measure_window",
    "player_block",
    "screen_rect",
]
