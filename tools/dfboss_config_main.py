"""Entry point for the standalone settings window, built as its own exe.

The settings window is its own program so it can be launched from a desktop shortcut
without a console window, and so opening it never depends on the game, the network,
or the overlay.

Usage:
    py tools\\dfboss_config_main.py
    py -m PyInstaller --onefile --windowed --paths src tools\\dfboss_config_main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if SRC_ROOT.is_dir() and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dfbossreminder.app import main  # noqa: E402 - after the path fix, on purpose

if __name__ == "__main__":
    raise SystemExit(main(["--config", *sys.argv[1:]]))
