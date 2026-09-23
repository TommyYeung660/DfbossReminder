# DFBossReminder

An overlay that tells you **which bosses are near the player right now**, on Dead
Frontier's own map coordinates — a bright green boss list hanging off the bottom of
the region minimap, inside the game's own window, with no backing box so the game
shows through.

This is a full rewrite of the old `DfbossReminder` (a Slack notifier driven by
`dfprofiler.com/bossmap`), keeping the data source and rebuilding everything else
on the engineering pattern of the sibling `DFLooterHelper`: pure decision logic
tested on any OS, fail-closed behaviour, and evidence instead of assumptions. The
old implementation is still in this repository's git history (the last commit that
had it is `stable version 2.3`).

## The readout

Over the game, the overlay is the boss list and nothing else — no header, no waypoint,
no age:

```text
1 x Charred Titan | 1048 x 1018 | 17:00
6 x Bandits | 1052 x 1018 | 5LD1
3 x Mega Mother | 1057 x 1016 | U1
```

The console prints the same rows with everything that explains them printed around them,
which is where you look when the list is empty and you need to know whether that is
because there are no bosses or because the feed is down:

```text
DFBossReminder  tommy660  1057,1017  27 個附近
  1 x Charred Titan | 1048 x 1018 | 17:00
  6 x Bandits | 1052 x 1018 | 5LD1
  Secronom Bunker | 1054 x 987 | 3LU30
  20 格內
  半徑外 154 個
  已更新 0 秒前
```

The list is drawn in **the client's own HUD font** and **right-aligned** against the
minimap, at 10 px with a **fully transparent background** — only the glyphs are
painted, with a single dark drop shadow behind them so they stay readable over bright
ground. The Chinese labels default on (`--language en` for English); the boss lines
themselves are the fixed format above. The one "extra" the overlay keeps is the row that
says how many bosses are **not** shown: it appears only when the window's maximum height
is actually hiding rows, which is the one silence that would be read as "that is the
whole list".

### Where the font comes from

The client's HUD font is **VIPER NORA** (Dimitris K., pOPdOG fONTS, 1999), and it is
not installed on the machine — it is baked into the client's Unity assets, which is
exactly why naming a font family would find nothing. So the tool takes it from the
client's own files:

* the asset is only **read**, the same read-only posture as everything else;
* the face is written to `~/.dfbossreminder/game-font.ttf` and loaded **privately**
  into the process (`FR_PRIVATE`), so nothing is installed and the player's font list
  is untouched;
* **nothing is redistributed** — the bytes come from the installation the tool is
  already reading, and they are never committed here.

VIPER NORA has no CJK glyphs, so the Chinese header and notes are drawn in a
CJK-capable face instead; each row picks by its own content, which is why the boss
lines look exactly like the game while the notes stay readable. `--font` overrides the
face, and `--no-game-font` uses an installed font only.

The face ships **one weight**, so `--font-weight` cannot make the text lighter than
the font is: weights 100 through 500 were measured to draw byte-identical pixels on
the game PC, and 700 and up make GDI synthesise a heavier face. The default 300 is
therefore the lightest this font gets — the readout reports the number it asked for
next to the one GDI gave back rather than claiming the strokes weigh that much, and
`tools/pc/probe-font-weight.py` is what measured it.

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
3. **Coordinate styles.** Name coordinates and the colour they should be drawn in, and
   a boss standing there is shown in that colour: `red=1015,999;1020,998` paints both
   cells red, `yellow=1057,1017:2` paints a cell and its eight neighbours. A style only
   changes the colour — nothing is hidden — and the first matching rule wins. Written in
   the settings window, or `--highlight "red=1015,999;1020,998"` on the command line.
4. **Draws it inside the game**, under the region minimap, as a layered
   click-through window that never takes focus (`--presentation overlay`), or outside
   the client (`--presentation panel`), or in the console.
5. **Is one program.** With no arguments it opens its settings window — the account id,
   the style rules, the font size, the colours, the placement and the big-boss names,
   every label in Traditional Chinese — and **開始** in that window runs the overlay in
   the same process, with **停止** (or closing the window) taking it down again. The font
   and the form scroll while the buttons stay put. It needs no game, no overlay and no
   network to open: it is how the account id gets set in the first place.
6. **Where it sits is yours to set.** The readout no longer follows the game window
   (asking for that was the player's fourth request: it moved the list under them while
   they were reading it) — the arrows in the settings window move it a step at a time,
   the step size is a box next to them, and the move is immediate while the overlay is
   up. `--anchor` and `--offset` do the same from a command line.
7. **Refuses to draw without the game.** The readout is a readout *of the running
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
| Domain (blocks, boss map parsing, coordinates and styles, settings, plan) | **235 tests pass** on the development machine |
| Profiler client (boss map, profile `gpscoords`) | **Verified live** against `dfprofiler.com` |
| Console presentation, polling loop, settings persistence, `--once`, `--json` | **Verified live** on the game PC |
| The overlay window and the client-rectangle locator | **Verified live on the game PC, 2026-09-22**: it appears over the client area, clicks pass through, and it does not take focus |
| The below-minimap placement, both line formats, and the settings window | **Verified live on the game PC, 2026-09-22** — see `docs/evidence/2026-09-22-overlay-below-minimap-on-client.png` |
| The refusal when the game is not running | **Unit-tested, not verified live** — the client was running during every session and closing it would have cost the player their game |
| The transparent 10 px readout, the Chinese labels and the content-sized window | **Verified live on the game PC, 2026-09-22** — see `docs/evidence/2026-09-22-overlay-transparent-on-client.png` |
| The client's own HUD font, extracted from its assets and loaded privately, and the right alignment | **Verified live on the game PC, 2026-09-22** — see `docs/evidence/2026-09-22-overlay-game-font-on-client.png` |
| The overlay as a bare boss list (no header, notes or age) and the font weight measurement | **Verified live on the game PC, 2026-09-23** — see `docs/evidence/2026-09-23-overlay-bosses-only-on-client.png` |
| Coordinate styles drawing a matching boss in its own colour, and the settings window driving the overlay | **Verified live on the game PC, 2026-09-23** — see `docs/evidence/2026-09-23-styles-red-yellow-surface.png` and `…-config-gui-audit-live.txt` |

The live Windows runs found seven defects no test on the development machine could
see (blank CJK glyphs, a truncated minutes column, a font lookup bound to the wrong
DLL, a long boss name elbowing out the coordinate, a truncated title, a fixed height
that clipped the notes, and invisible glyphs on a transparent surface because GDI
never writes the alpha byte); all seven are fixed and recorded in
`docs/verified-facts.md`, along with the exact observations and what is still open.

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

To set the style rules, the font size and the colours by clicking rather than typing
(and to start the overlay from the same window):

```sh
uv run dfboss --config
```

### Useful commands

```sh
# one look, no window - prints the plan and exits
uv run dfboss --once --json plan.json

# show a named coordinate in red: the boss is still listed, just painted
uv run dfboss --highlight "red=1015,999;1020,998" --highlight "yellow=1057,1017:2"

# drop every style rule again
uv run dfboss --once --no-highlights

# what is set right now
uv run dfboss --show-config

# 20 blocks, refreshed every 30s, with a boss of your own counted as big
uv run dfboss --radius 20 --poll 30 --big-boss Dreadstag

# somewhere else on screen instead of under the minimap, in a larger font
uv run dfboss --anchor top-left --width 430 --font-size 14 --align left

# left-aligned text, and without the client's own font
uv run dfboss --align left --no-game-font
```

There is no in-game hotkey any more: the only one there ever was toggled whitelist
mode, and the whitelist is gone (the coordinate styles replaced it). Start, stop and
position all live in the settings window, which is what a double-click opens.

## How it reads

Read-only, always:

* it makes `GET` requests to `dfprofiler.com` — the boss map and one profile;
* it measures the game window's client rectangle to place the overlay, once, at start -
  it does not keep watching it;
* it never injects into the client, never reads or writes game memory, never sends
  keyboard or mouse input to anything, and never posts anything anywhere. There is no
  hotkey and no injected input at all since 2026-09-23: the overlay is a window that
  draws itself and takes no input, and the only controls are the buttons in its own
  settings window.

The same boundary as the sibling project, for the same reason: a tool that only
reads cannot change your account's gameplay, and the rules question stays a rules
question rather than becoming an automation one.

## Layout

```text
src/dfbossreminder/domain/     pure decision logic (stdlib only, runs on any OS)
src/dfbossreminder/services/   the dfprofiler client, the game-window rectangle,
                               and the client's own font read out of its assets
src/dfbossreminder/ui/         the layered click-through overlay, its placement, the rows
src/dfbossreminder/app.py      the process: settings, poll loop, presenters, CLI
tools/pc/                      Windows-side scripts: build the exe, run it, probe the client
docs/system-design.md          the design, the decisions, and what each one rejects
docs/verified-facts.md         fact ledger with sources and open questions
docs/windows-runbook.md        step-by-step instructions to run it on the game PC (Chinese)
```

## Development

```sh
uv run pytest                      # 194 domain, service, ui and app tests
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
