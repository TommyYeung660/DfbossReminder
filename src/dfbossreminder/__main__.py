"""``python -m dfbossreminder`` runs the tool without installing its script.

With no arguments it opens the settings window, like the packaged exe: the tool is
one program whose face is that window.
"""

from __future__ import annotations

from .app import main

if __name__ == "__main__":
    raise SystemExit(main(default_to_config=True))
