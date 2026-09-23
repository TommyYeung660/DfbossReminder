"""Entry point for the packaged exe and for a checkout that was never installed.

PyInstaller is pointed at a script, not a module, so this exists as the one file the
build names. It puts the project's ``src`` on ``sys.path`` first, which makes the same
file work whether it is frozen (``src`` is beside it in the bundle) or run straight
from a checkout.

It is also the only entry point the player uses: with no arguments it opens the
settings window, which is where the overlay is started from. Anything on the command
line is the diagnostic path.

Usage:
    py tools\\dfboss_main.py                 (double-click: the settings window)
    py tools\\dfboss_main.py --once
    py -m PyInstaller --onefile --paths src tools\\dfboss_main.py
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
    # ``default_to_config``: a bare double-click opens the settings window rather than
    # printing a usage error, and the window can start the overlay itself.
    raise SystemExit(main(default_to_config=True))
