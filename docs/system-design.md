# DFBossReminder System Design

## 1. Requirement

> 1. 可以記下 user id, 即 14008279 格式的 df user id
> 2. 根據玩家實時座標, 標出附近方圓一定距離(可動態設置)的 boss 的座標
> 3. 可以開啟白名單模式, 在白名單的座標如出現 boss 才顯示
> 4. 如果可以的話, 直接在遊戲界面做 overlay, 像現時遊戲中的 buff 數據

Then, after the first live run:

> 1. 我要求overlay 在遊戲視窗里, minimap 的下方用亮綠色顯示list 出來, 字體大小約12px, 格式是:
>    `6 x Bandits | 1052 x 1018 | 5LD1`
>    如果是big boss / ultra boss: `Devil Hound | 1052 x 1018 | 18:00`
>    注,18:00 是完結時間
> 2. 程序要有獨立配置界面去做白名單以及overlay字體大小/顏色配置
> 3. 如果遊戲主程序沒開, overlay 不允許開啟

Read as engineering statements:

* **R1** — an account id in the `14008279` form is entered once and remembered.
* **R2** — using the player's live coordinates, show the bosses within a
  configurable radius of them.
* **R3** — a whitelist mode: when it is on, only bosses at whitelisted
  coordinates are shown.
* **R4** — an in-client overlay under the region minimap, bright green, ~12 px, in a
  fixed line format, with a second format for big/ultra bosses that shows the end
  time instead of a bearing.
* **R5** — a settings window for the whitelist, the font size and the colours.
* **R6** — no game running, no overlay.

## 2. The facts this design turns on

All of them are recorded with sources in `docs/verified-facts.md`; the ones that
decide the architecture are here.

| Fact | Consequence |
| --- | --- |
| The boss map (`/bossmap/json/`) lists each event's spawn blocks as `["x","y"]` string pairs, in the map's own coordinate grid (measured live: a 60-minute city cycle listing 29 blocks around `1000–1060 x 981–1020`) | The boss side of R2/R3 is a set of map blocks |
| A profile (`/profile/json/<id>`) publishes `gpscoords: ["1057","1017"]` — the account's map block, in that same grid | The player side of R2 is a map block, and it is addressed by account id — which is exactly what R1 asks to remember |
| The client's in-memory player position is **block-local**, not a map coordinate (measured: world `(48.27, 38.89)` while the map read `1057 x 1017`) | Reading game memory cannot answer R2: the two numbers are in different spaces and cannot be compared |
| The client has no plugin API, and the sibling project's boundary is read-only observation with no injection, no memory writes and no input | Any in-client rendering must be an external overlay window, not a mod (D1) |
| `gpscoords` is the account's *last known* block; the profiler only publishes it while the game has reported one | "Real-time" means "as fresh as the profiler is", so freshness must be visible, not assumed (D6) |

### 2.1 Why the in-memory position is not used, stated plainly

The obvious reading of "real-time coordinates" is "read them from the running
client", and the sibling project proves that is possible. It is not usable here, and
the measurement above is why: the client's position is local to the block the player
is standing in, so `(48.27, 38.89)` and `1057,1017` are the same place in two
different coordinate systems. Comparing an in-memory position with a boss's map
block would be arithmetic on two unrelated numbers, and the result would look
plausible while being wrong — the worst kind of failure this project can have.

The map block is therefore the only coordinate this tool uses, for both sides, and
it comes from the one source that publishes it: the profiler, keyed by the account
id that R1 asks to remember.

A future in-memory global-coordinate reader would slot in behind
`services.profiler.player_block` without touching the domain, and would be adopted
only with a recorded measurement that it agrees with the map.

### 2.2 The last three decisions this section needed, and where the data came from

**The coordinate readout is trimmed, never assumed.** Which bosses are "big" or
"ultra" is **not in the boss map**: the payload has a name, a count, spawn blocks and
two timestamps, and nothing that grades a boss. The wiki's *Bosses* page carries the
grading in prose — threat levels 1–8, plus "Special Daily Bosses" which are "extra
tough", spawn once per day, and stay for up to three hours instead of one. The tier
is therefore a **configured name list**, defaulting to those three (Devil Hound,
Volatile Leaper, Behemoth), editable in the settings window. The alternative —
guessing a tier from the quote count or the duration — would be a number that looks
like a fact and is not one.

**The bearing encoding was derived, then confirmed.** ``5LD1`` is
``{n}L|R`` followed by ``U|D{n}``: five blocks left and one down. That reading comes
from the example itself — the player was at ``1057,1017`` and the boss at
``1052,1018``, which is ``5`` left and ``1`` down — so it is checked rather than
guessed, and the format is pinned by a test with those exact numbers.

**The minimap rectangle was measured, not assumed.** ``(1060, 10, 215)`` in client
coordinates, read off a live 1280x720 client capture: the minimap's own ``BUNKER``
header sits at its top and its ``1057 X 1017`` readout at its bottom, which brackets
the rectangle from both sides. It also matches the value the sibling project measured
independently.

## 3. Decisions

### D1 — An external click-through overlay, never a mod

R4's "overlay in the game interface" is produced by a separate topmost window over
the client area, drawn per-pixel with `UpdateLayeredWindow`, with
`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST`: clicks
pass through to the game, the window never takes focus, and it stays out of the
taskbar and alt-tab.

Rejected: injecting a DLL or hooking Mono so the client draws it itself. There is no
plugin API, so that route is injection by definition, and it is exactly the boundary
the sibling project draws (read-only, no injection, no memory writes). It would also
break on every client update.

The same window serves R4 and the safer presentation: `--presentation overlay`
anchors it to the game's client rectangle, `--presentation panel` anchors it to the
screen instead, and both are the same code with a different rectangle.

### D2 — One coordinate system, from the profiler, keyed by the remembered id

The player's block and the bosses' blocks both come from `dfprofiler.com`, in the
game's map grid. `services/profiler.py` fetches; `domain/` does all the arithmetic.
R1's remembered id is what makes the player side possible at all.

### D3 — The radius and the whitelist both live in the plan, as pure rules

`domain/plan.py` is a pure function of `(events, player, settings, now)`. The radius
test uses the **block** count (`chebyshev`), because that is how a player walks, and
the ordering uses the straight-line distance only to break ties between cells that
are equally many blocks away, so the order never contradicts the count a row prints.

**In whitelist mode the whitelist is the filter, and the radius does not apply.** A
watched coordinate is reported wherever the player is — that is the whole point of
watching one — and combining the two filters would make whitelist mode mostly
useless. Whitelist mode with an empty list shows nothing and says so, rather than
falling back to showing everything, which would be the opposite of the mode.

### D4 — Fail closed, and never invent a value

| Condition | Behaviour |
| --- | --- |
| No account id configured | refuse to start (interactive) and print the command that sets one |
| No `gpscoords` for the account | draw no distances, say `no player position`, list nothing when told to |
| Boss map fetch fails | keep the last good plan, mark it stale, and say how old and why |
| Fetch fails before any success | draw no rows, say `no data yet: <reason>` |
| Not Windows, or the overlay cannot be created | fall back to the console and print the reason |
| Game window not found | anchor to the screen and note it; do not refuse to draw |
| Client covers the whole monitor | note the fullscreen risk; do not guess that it is fullscreen |

A windowed overlay cannot be drawn over an exclusive-fullscreen swap chain, so that
case is reported rather than worked around.

### D5 — Settings that stick, per field

`domain/settings.py` reads the JSON settings file with **per-field fallback and
clamping**: one bad value never discards the rest, and a number that is out of range
is clamped rather than rejected. `parse_settings` and `to_dict` are inverses, which
is what lets `--user-id 14008279` write a file this module reads back unchanged — the
mechanism behind R1. Anything given on the command line is remembered unless
`--no-save` is passed, so the player sets these once.

### D6 — Freshness is shown, not assumed

Every draw carries how long ago the data was fetched, and a plan older than
`stale_seconds` is marked stale and coloured as a warning. `gpscoords` is the
account's last known position, and a tool that hid that would let the player walk
toward a stale bearing without knowing it.

### D8 — The readout is trimmed to the width, and the name is what gives way

The first cut of the new format used a fixed name budget, and the live run showed
what that costs: a joined multi-boss name (``1 x Evolved Longarms + 1 x Irradiated
Evolved Longarms``) ran past the panel, and the window's own ellipsis then ate the
block coordinate and the bearing — the two fields the row exists for. The name budget
is now computed from the configured width and font size, minus everything that
follows the name, so the coordinate and the third field can never be the fields that
disappear. A test asserts that every row drawn at the shipped size fits the shipped
width.

### D9 — The settings window is its own program

``--config`` opens a tkinter window; ``DFBossReminderConfig.exe`` is built
``--windowed`` so it opens from a shortcut with no console behind it. It is
deliberately independent of the overlay: it needs no game, no network, and it never
creates a window over the client. The value-building and validation are plain
functions, so "load, show, save" round-trips are tested without a display, and a value
the tool had to change is *reported* rather than silently stored.

tkinter rather than a packaged toolkit: it is in the standard library, so it keeps
the project's zero runtime dependencies and the PyInstaller build small, and a
settings form does not need more.

### D11 — A transparent surface needs its glyph pixels made opaque

Worth recording, because it is invisible from the code: **GDI's text drawing does not
write the alpha byte.** On an opaque surface that is harmless, since the backing left
255 there. On a surface cleared to `alpha 0` — which is what a fully transparent
backing is — the glyphs are drawn and then composited away by
`UpdateLayeredWindow`, so the readout is present, correct, and completely invisible.
The live run found it by crashing the surface dump rather than by showing nothing,
which is a reminder that a diagnostic that fails loudly beats a feature that fails
quietly.

The fix tests each pixel for "not zero" and gives it a full alpha. That test is exact
because the surface is cleared to exactly zero first, and it is why the shadow colour
is near-black rather than black: a pure black shadow would be drawn and then discarded
by the same rule.

### D14 — The client's font is taken from the client, not shipped

The readout is meant to look like the game, and the game's HUD font turned out to be
**VIPER NORA** - a 1999 freeware face baked into the client's Unity assets and not
installed on any machine, so naming it would find nothing. Three ways to close that
gap, and why the third was chosen:

* **name a similar installed font** - cheap, and wrong: the whole request is that it
  looks like the game, and it would not;
* **ship the TTF** - it renders exactly, but it redistributes someone else's font on a
  licence that was written for embedding in a game, not for a third-party tool;
* **read it out of the client's own installation** - exact, read-only, and nothing is
  redistributed: the bytes come from the copy of the game the tool is already reading,
  they are cached in this project's own state directory, and they are loaded with
  ``FR_PRIVATE`` so no font is installed and the player's font list is untouched.

The extractor's rule is what makes it safe on a 200 MB asset: a candidate font header
counts only when its **own** ``name`` table contains the family being looked for, so a
coincidental ``\x00\x01\x00\x00`` sequence cannot win. That rule is tested against
a TrueType file the test builds itself, which is the only way to test an extractor
whose real input cannot be shipped.

### D15 — Two faces, chosen per row

VIPER NORA has no CJK glyphs, so the Chinese header and notes cannot be drawn in it -
they come out as empty boxes. Rather than give up either the game's look or the
Chinese labels, the overlay keeps two faces and each row picks by its own content:
boss lines (ASCII) in the client's font, rows containing Chinese in a CJK face.
Without this the readout would be perfect boss lines sitting above four lines of
boxes.

### D16 — The weight is reported, the shadow is what lightens the text

The readout was asked for `font-weight: 300`. Reading the font's metadata answers a
different question than the one being asked: it declares a single face
(`OS/2 usWeightClass` 400, subfamily "Regular"), so *"is there a lighter outline to
select?"* is **no** — but that says nothing about whether GDI honours the number
anyway. It does: `GetObjectW` echoes 300 straight back, so the read-back cannot be
used as evidence of the drawn strokes either.

The probe therefore measures pixels instead of trusting either signal, and found a
three-band reality: **100 through 500 render byte-identically** (one MD5, one ink
count), and **700 and up make GDI synthesise a heavier face** even though the family
has no bold. Two consequences the code follows:

* the readout reports what it asked for *next to* what GDI returned, and never claims
  the strokes weigh that number — the honest reading is "300 is at the floor";
* the visible lightening came from the **shadow**, not the weight. Four one-pixel
  offsets put dark fringe on all four sides of every glyph, which at 10 px presses
  against every stem and reads as emboldening; one offset keeps the fringe on a single
  side. That is why the weight change alone would have been imperceptible.

This is the general shape of a Windows-only cosmetic setting: the request, the
recorded value and the drawn pixels are three different things, and only the third is
what the player sees.

### D17 — The overlay is the answer; the console is the explanation

The window over the game now draws **only the boss rows**: no header, no waypoint, no
notes, no age, and no reserved band for a title. That is what the player asked for, and
it is a reasonable thing to want - the header repeats what the minimap already shows and
the notes are diagnostics, not something to read while fighting.

The risk it creates has to be answered somewhere, because the removed lines were exactly
the ones that told a correct empty readout from a broken one: "20 格內 / 半徑外 154 個 /
已更新 0 秒前" is how a person knows the feed is alive. So the split is now explicit:

* the **overlay** is the answer - the list, and nothing else;
* the **console** is the explanation - the same rows with the header, the notes and the
  age around them, and it is what `--once`, the runbook and every log show.

Rows are filtered by one flag (`view.rows_for(..., extras=False)`), not by two row
builders, so the two renderings cannot drift: a test asserts that every overlay row
appears in the console rendering. One exception survives in the overlay, deliberately:
the "還有 N 行未顯示" row, which appears only when the maximum height is genuinely
hiding bosses. Silence there would read as "that is the whole list", which is the one
misreading the overlay cannot afford.

### D18 — A regression the tests could not see, because they built the object the wrong way

Commit `d409401` moved the font work into `_game_font_face` and left the hotkey
registration **after one of its `return`s**. The overlay kept working, the ledger kept
saying "F8 really registers as a global hotkey", and the live runs after that commit
simply no longer printed the line that would have shown otherwise - nobody was looking
for its absence.

The unit tests did not catch it either, and that is the interesting part: they build the
presenter with `OverlayPresenter.__new__(...)` and set the attributes by hand, because
the real constructor wants a game window and a Windows overlay. `__init__` was therefore
never executed by any test, so a statement that never runs is invisible to all of them.

Two changes: the registration is its own method called from `__init__`, and a test
constructs the presenter **the way the tool does** - stub overlay class, stubbed window
lookup, real constructor - asserting the key was taken and that a refusal is reported
rather than swallowed. `tools/pc/probe-config-gui.py` and the hotkey probe fill the same
role on the machine: the line is in the run log, and its absence is now a thing to check
rather than a detail.

### D12 — The window follows its content

The height was a fixed setting, and the live run showed it clipping the *notes* at the
bottom of the list — the one part that says whether an empty readout is correct or a
bug, so the worst possible thing to lose silently. The window now sizes itself to what
it has to show, up to the configured height as a maximum, and anything still over that
limit appears as a final line saying how many lines were hidden.

### D13 — The toggle key is a setting

The whitelist toggle needs a global hotkey, and a hotkey another application already
holds cannot be registered — the toggle then does not exist for the player. On the
game PC the first attempts failed, which turned out to be two of this project's own
overlays competing rather than a conflict with another program; F8 is in fact free
there and only F12 is taken. The key is configurable anyway, and
`tools/pc/probe-hotkeys.py` answers "which are free" for any machine.

### D10 — No game, no overlay

The overlay is a readout *of the running client*: it is anchored to the client's
rectangle and it reports where that client's player is. With the client closed there
is no rectangle to anchor to and no player to measure, so the window is not opened at
all. This is enforced by refusing at construction (``GameNotRunning``, exit code 3)
and by deliberately **not** letting ``make_presenter``'s fallback-to-console path
swallow it — a silent fallback would ignore the presentation the player chose. The
console presentation is never gated, because checking the tool before starting the
game is what it is for.

### D7 — The fetch is a `GET`, and the clock and the network are injected

The profiler client takes a `transport` callable, so the parsing and the whole
refresh are tested against the recorded payloads in `tests/fixtures/` with no
network, and the domain takes `now` as an argument so "an expired boss is not
shown" is a test rather than a race.

## 4. Architecture

```text
        settings.json  (+ command line overrides)
                    |
        [services] dfprofiler GET  --->  boss map + profile (gpscoords, account name)
                    |
        [domain] parse -> events -> sightings
                    |
        [domain] plan:  whitelist? -> radius? -> nearest first -> cap
                    |
        [ui] rows (text + colour) --> overlay window (client area or screen) | console
```

| Module | Responsibility | Runs/tests on macOS |
| --- | --- | --- |
| `domain/geometry.py` | `Block`, chebyshev/euclidean, the bearing words | yes |
| `domain/bosses.py` | boss-map parsing, `BossEvent`, `Sighting`, `expand` | yes |
| `domain/whitelist.py` | whitelist parsing, matching, JSON form | yes |
| `domain/settings.py` | validated settings, clamping, round trip | yes |
| `domain/plan.py` | the whitelist/radius/ordering/cap rules, the tier, the notes | yes |
| `services/profiler.py` | the two `GET`s, `player_block`, `fetch_state` | yes (with a fake transport) |
| `services/window.py` | game client rectangle, screen size, fullscreen risk | types only |
| `ui/layout.py` | anchor → top-left corner arithmetic | yes |
| `ui/panel.py` | the layered click-through overlay window | contract tests only |
| `ui/view.py` | plan → text rows, the two formats, the width budget, the colours | yes |
| `ui/config_gui.py` | the settings window; its data half is pure and tested | the data half |
| `app.py` | settings, poll loop, presenters, CLI, fail-closed | yes (with fakes) |

### 4.1 Data contracts

```text
Block            { x, y }
Bearing          { dx, dy }        -> blocks, horizontal, vertical, describe(style)
BossEvent        { game_id, name, amount, blocks[], start, end, boss_num, event_type, title }
Sighting         { event, block }                       # one place, one boss
WhitelistEntry   { block, radius, label }               # contains(block)
Settings         { user_id, radius_blocks, whitelist_mode, whitelist[], ... }
BossRow          { name, block, amount, is_mission, distance, bearing, minutes_left, whitelisted }
Plan             { rows[], player, notes[], counts... }
Row              { text, colour, bar? }                 # the overlay's input
```

### 4.2 One pass

```text
tick(now):
  if now >= next_fetch:      refresh()            # GET bossmap + profile, or record the error
  if now >= next_window_check: follow()           # re-anchor to the client rectangle
  if the toggle hotkey was pressed: flip whitelist mode and save
  draw(plan(now), status(now))                    # build the plan, then draw it
```

## 5. What is verified, and what is not

Verified live on the development machine, 2026-09-22, against `dfprofiler.com`
(full records in `docs/verified-facts.md`):

* the boss-map and profile schemas, the `gpscoords` format, and the two coordinate
  spaces;
* `--once` printing a real plan: player `1057,1017`, five bosses within 6 blocks,
  each with a bearing and a distance, and a JSON export carrying the counts;
* whitelist mode: one entry (`1054,987:3`) suppressing 159 of 162 sightings and
  showing three bosses 28–32 blocks away, i.e. outside the radius — the whitelist
  overriding it, as designed;
* 144 tests green, including the contract tests that pin the overlay's style flags and
  that neither Windows module calls anything that writes or sends input.

Verified live on the game PC, 2026-09-22 (client windowed at 1280x720 at
`(242,134)`), with the artifacts in `docs/evidence/`:

* **the overlay is drawn over the game's own client area** — it reports
  `visible=True at (256,148)-(686,388)`, which is exactly the client origin inset by
  the configured 14 px — and it is visible in a capture of that client area;
* the game's **own minimap read `1057 X 1017`** while the readout's header read
  `1057,1017`, which is the independent cross-check that the profiler's `gpscoords`
  is the coordinate the client itself displays;
* **clicks pass through and focus is not taken**: `WindowFromPoint` at the overlay's
  centre resolved to the window underneath, and the foreground window was unchanged;
* the client-rectangle measurement is correct on that machine at its scaling
  (`tools/pc/probe-window.py`);
* the transparent 10 px readout renders with the game showing through, the labels are
  Chinese, and the window sizes itself so the notes are not clipped.

Not verified — and not claimed:

* borderless-windowed presentation, and a display with DPI scaling;
* whether the overlay follows the client when the window is *moved* (the re-anchor
  runs on a timer, but no run has recorded a move);
* whether `gpscoords` updates as often as the player expects — it is the account's
  last known position, so the tool shows the age rather than assuming a cadence.

## 6. Risks and open questions

* **Profiler freshness.** `gpscoords` is the account's last known block. If the game
  reports it rarely, a boss bearing is measured from where the player *was*. The
  panel shows the age; the honest fix would be an in-memory global-coordinate reader
  (§2.1), which does not exist yet.
* **Rules risk.** Whichever way it is built, a third-party tool that reads the game
  or its community data is a rules question the operator owns. This tool sends no
  input and changes no gameplay, which keeps it in the read-only category; drawing
  over the client is the one place it is more intrusive than the sibling project's
  side panel, which is why the safer presentation is always available.
* **Fullscreen.** An overlay cannot be drawn over exclusive fullscreen. Reported,
  not worked around.
* **The boss map is a third party's output.** A schema change must surface as
  "fewer bosses found" (the parser is defensive and the tests use a real payload),
  never as a wrong coordinate.
* **Client updates.** Nothing here reads client memory or offsets, so a client
  update does not break it — that is a benefit of D2 over the in-memory route.

Open questions for the first game-PC session:

1. Does the overlay appear over the client in windowed and borderless-windowed mode,
   and does it stay above the game while the client is focused?
2. Does the client rectangle returned by `GetClientRect` + `ClientToScreen` place
   the overlay exactly where intended, at the display's DPI scaling?
3. Does a click over the overlay reach the game, and does the game keep keyboard
   focus while the overlay is up?
4. With a non-empty whitelist and the toggle, does `F8` flip the mode in the panel
   within a frame?
