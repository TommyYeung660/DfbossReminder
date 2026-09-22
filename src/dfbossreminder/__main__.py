"""``python -m dfbossreminder`` runs the tool without installing its script."""

from __future__ import annotations

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
