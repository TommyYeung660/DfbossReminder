# DFBossReminder

An overlay that tells you **which bosses are near the player right now**, on Dead
Frontier's own map coordinates — a bright green boss list hanging off the bottom of
the region minimap, inside the game's own window.

This is a full rewrite of the old `DfbossReminder` (a Slack notifier driven by
`dfprofiler.com/bossmap`), keeping the data source and rebuilding everything else
on the engineering pattern of the sibling `DFLooterHelper`: pure decision logic
tested on any OS, fail-closed behaviour, and evidence instead of assumptions. The
old implementation is still in this repository's git history (the last commit that
had it is `stable version 2.3`).

## The readout

```text
DFBossReminder  1057,1017  27 nearby
Charred Titan | 1048 x 1018 | 17:00
6 x Bandits   | 1052 x 1018 | 5LD1
3 x Mega Mother | 1057 x 1016 | U1
Secronom Bunker | 1054 x 987 | 3LU30
within 20 blocks
```

A normal boss is one you walk to, so the third field is where it is from you:
``5LD1`` is five blocks left and one down, and ``U``/``D`` are up and down on the
boss map. A **big/ultra boss** is a special spawn with a long window, so its third
field is the time it despawns instead — ``17:00`` is the end time, not the start.
The block is always absolute, which is what makes a row checkable against the game's
own minimap readout (the capture in `docs/evidence/` shows both saying `1057,1017`).

Which bosses count as big is a **name list**, because the boss map publishes no
tier: the default is the wiki's Special Daily Bosses (Devil Hound, Volatile Leaper,
Behemoth — extra tough, one spawn a day, up to three hours), and the settings window
is where you add your own.

## What it does

1. **Remembers your account id.** The numeric Dead Frontier account id
   (`14008279`), set once with `--user-id` and stored in a settings file. It is what
   the profiler publishes your live map position under.
2. **Shows the bosses within a radius of your live position**, nearest first, with
   the blocks between you and them. The radius is a setting (`--radius`), changeable
   at any time.
3. **Whitelist mode.** Turn it on and only bosses at coordinates you list are
   shown, wherever you are on the map. `1055,986` watches one cell,
   `1055,986:2` watches that cell and everything within two blocks of it.
4. **Draws it inside the game**, under the region minimap, as a layered
   click-through window that never takes focus (`--presentation overlay`), or outside
   the client (`--presentation panel`), or in the console.
5. **Opens its own settings window** (`--config`): the whitelist as a table, the font
   size, the colours, the placement and the big-boss names. It needs no game, no
   overlay and no network — it is how the account id gets set in the first place.
6. **Refuses to draw without the game.** The readout is a readout *of the running
   client*, placed against its client area and measured from its player, so with the
   client closed the overlay is not opened at all and the reason is printed. The
   console presentation is unaffected, which is how the tool is checked before a game
   is started.

The player's position and the boss list both come from Dead Frontier's own map
coordinate system, so they are directly comparable. The client's in-memory
position is *not* used for this, and deliberately so: it is local to one block
(measured live: world `(48.27, 38.89)` while the map read `1057 x 1017`), so it
cannot be compared with a map coordinate at all. See `docs/system-design.md` D2.

## Status

| Piece | State |
| --- | --- |
| Domain (blocks, boss map parsing, whitelist, settings, plan) | **165 tests pass** on the development machine |
| Profiler client (boss map, profile `gpscoords`) | **Verified live** against `dfprofiler.com` |
| Console presentation, polling loop, settings persistence, `--once`, `--json` | **Verified live** on the game PC |
| The overlay window and the client-rectangle locator | **Verified live on the game PC, 2026-09-22**: it appears over the client area, clicks pass through, and it does not take focus |
| The below-minimap placement, both line formats, and the settings window | **Verified live on the game PC, 2026-09-22** — see `docs/evidence/2026-09-22-overlay-below-minimap-on-client.png` |
| The refusal when the game is not running | **Unit-tested, not verified live** — the client was running during every session and closing it would have cost the player their game |

The live Windows runs found five defects no test on the development machine could
see (blank CJK glyphs, a truncated minutes column, a font lookup bound to the wrong
DLL, a long boss name elbowing out the coordinate, and a truncated title); all five
are fixed and recorded in `docs/verified-facts.md`, along with the exact observations
and what is still open.

## Install and run

```sh
uv sync
uv run dfboss --user-id 14008279 --radius 8            # remembers the id, then runs
```

Without an install, from a checkout:

```sh
PYTHONPATH=src python3 -m dfbossreminder --user-id 14008279
```

The first run with `--user-id` saves it, so every run after that is just:

```sh
uv run dfboss
```

To set the whitelist, the font size and the colours by clicking rather than typing:

```sh
uv run dfboss --config
```

### Useful commands

```sh
# one look, no window - prints the plan and exits
uv run dfboss --once --json plan.json

# watch a watchlist instead of a radius
uv run dfboss --whitelist "1055,986:2=Bunker;1057,1017" --whitelist-mode on

# what is set right now
uv run dfboss --show-config

# 20 blocks, refreshed every 30s, with a boss of your own counted as big
uv run dfboss --radius 20 --poll 30 --big-boss Dreadstag

# somewhere else on screen instead of under the minimap, in a larger font
uv run dfboss --anchor top-left --width 430 --font-size 14
```

While it runs, **`F8` toggles whitelist mode** and remembers it. The toggle needs
the overlay window, so it is available in `overlay` and `panel` mode, not in the
console.

## How it reads

Read-only, always:

* it makes `GET` requests to `dfprofiler.com` — the boss map and one profile;
* it measures the game window's client rectangle to place the overlay;
* it never injects into the client, never reads or writes game memory, never sends
  keyboard or mouse input, and never posts anything anywhere. The `F8` hotkey is
  the OS handing a key *you* pressed to its own window.

The same boundary as the sibling project, for the same reason: a tool that only
reads cannot change your account's gameplay, and the rules question stays a rules
question rather than becoming an automation one.

## Layout

```text
src/dfbossreminder/domain/     pure decision logic (stdlib only, runs on any OS)
src/dfbossreminder/services/   the dfprofiler client and the game-window rectangle
src/dfbossreminder/ui/         the layered click-through overlay, its placement, the rows
src/dfbossreminder/app.py      the process: settings, poll loop, presenters, CLI
tools/pc/                      Windows-side scripts: build the exe, run it, probe the client
docs/system-design.md          the design, the decisions, and what each one rejects
docs/verified-facts.md         fact ledger with sources and open questions
docs/windows-runbook.md        step-by-step instructions to run it on the game PC (Chinese)
```

## Development

```sh
uv run pytest                      # 165 domain, service, ui and app tests
uv run dfboss --once               # a live look, no window
```

The domain layer takes its clock and its network by injection, so the whole
decision is testable without a game, a network, or Windows. The Windows-only
surface is two modules wide (`ui/panel.py`, `services/window.py`) and both bind
their API inside a function, so importing the package on a Mac never fails.

## The old version

The previous implementation — a Slack bot that polled the boss map and the profile
JSON on a schedule — is in git history and was removed from the working tree by
this rewrite. Nothing about its behaviour is inherited except the two data sources,
which are the same URLs this version reads.
