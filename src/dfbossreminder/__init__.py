"""DFBossReminder: show the bosses near the player, on top of the game.

The project is split so that everything it decides is pure Python that runs and
is tested on any OS:

* ``domain/``    - block arithmetic, boss-map parsing, the whitelist, settings and
                   the display plan. Standard library only, no clock, no network.
* ``services/``  - the two outside worlds: the dfprofiler HTTP API and the game
                   window's client rectangle. Both take their side effect by
                   injection so the tests never touch the network or Windows.
* ``ui/``        - a layered, click-through overlay window and a console printer.
* ``app.py``     - the process: read settings, poll, plan, draw, fail closed.
"""

from __future__ import annotations

__version__ = "0.1.0"
