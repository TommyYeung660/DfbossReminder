# DFBossReminder Verified Facts

Working fact ledger. Evidence levels:

* **Recorded live** — observed against the real service or the real client, with the
  raw values kept here or in `docs/evidence/`.
* **Measured upstream** — measured by the sibling project `DFLooterHelper` against
  the running client; a lead, re-usable here because it is about the same client.
* **Implementation fact** — this source does it and its tests pass.
* **Not live verified** — no run has established it yet.
* **Open question** — explicitly unknown; the first game-PC session answers it.

## The two data sources

| Fact | Level | Source |
| --- | --- | --- |
| `https://www.dfprofiler.com/bossmap/json/?_=<ms>` returns a JSON object keyed by event index; each value is one event | Recorded live | fetch 2026-09-22, 25 entries, 14,257 bytes |
| An event's `locations` is a list of two-element **string** pairs, e.g. `[["1000","1004"]]`; a 60-minute city boss cycle listed 29 of them | Recorded live | same fetch, `game_id` 13 = `1 x Flaming Mother`, 29 locations |
| An event's boss name is `special_enemy_type` (e.g. `4 x Bandits`), the count is `special_enemy_amount`, and `boss_num` is non-zero for a cycle entry and `0` for a mission | Recorded live | same fetch |
| Mission events carry `event_type: "mission"` and a `title`; cycle events have `event_type: ""` | Recorded live | `game_id` 0/2 (mission, `The Flames`/`Flamin' Stenches`) vs `game_id` 5–19 (cycle, no title) |
| `start_time` and `end_time` are unix seconds, published as strings; a city cycle is 60 minutes, a mission window was 695 | Recorded live | 14:00→15:00 for the cycle entries, 04:20→15:55 for the missions |
| The endpoint needs the page's headers (`Referer`, `X-Requested-With: XMLHttpRequest`); without them it answers with HTML, not JSON | Implementation fact | `services/profiler.py`, and the previous tool's code carries the same headers |
| `https://www.dfprofiler.com/profile/json/<user_id>?_=<ms>` returns one account; `gpscoords` is `["1057","1017"]` and `override.account_name` is the display name | Recorded live | `user_id` 14008279 → `gpscoords` `["1057","1017"]`, `account_name` `tommy660`, 2026-09-22 |
| `gpscoords` is the account's **last known** map block; it is unchanged between sessions when the account has not moved in-game | Recorded live | the same value on 2026-09-22 as the sibling project recorded live on 2026-09-18 |

## The coordinate spaces — the fact the design turns on

| Fact | Level | Source |
| --- | --- | --- |
| The boss map's `locations` and a profile's `gpscoords` are the **same** grid, and it is the game's map coordinate: both read around `1000–1060 x 981–1020` for the same district | Recorded live | boss fetch and profile fetch, 2026-09-22 |
| The client's in-memory player position is **block-local**, not a map coordinate: world `(48.2728, -0.0002, 38.8946)` while the map read `1057 x 1017` | Measured upstream | `DFLooterHelper/docs/evidence/builds/client-layout-2026-09-18.json`, `player_position` |
| A 3D district is roughly the size of nine 2D cells, so one district spans a few map blocks | Wiki-sourced | `DFLooterHelper` wiki note (*Inner City*, *Points of Interest*) |
| Therefore an in-memory position cannot be compared with a boss's map block, and this tool does not try | Implementation fact | `docs/system-design.md` §2.1 |

## What this implementation does, and its tests

| Fact | Level | Source |
| --- | --- | --- |
| `--once` prints a real plan for account 14008279 at block `1057,1017`: 5 bosses within 6 blocks, leader `3 x Irradiated Titan` at `1058,1016`, distance 1, bearing `1右1上` | Recorded live | 2026-09-22, `--radius 6` |
| Whitelist mode suppresses by coordinate, not by radius: one entry `1054,987:3` suppressed 159 of 162 sightings and showed 3 bosses at 28–32 blocks | Recorded live | 2026-09-22, `--whitelist "1054,987:3" --whitelist-mode on` |
| The count of sightings and of those beyond the radius are exported, so a filter can be audited after the fact | Recorded live | the `--json` export carries `counts.total_sightings` 162, `beyond_radius` 157 |
| The radius test is the block count (`chebyshev`), so a diagonal neighbour is one block | Implementation fact | `domain/geometry.py`, `tests/test_geometry.py` |
| A mission is excluded unless `include_missions` is set | Implementation fact | `domain/bosses.py`, `tests/test_bosses.py` |
| The whitelist overrides the radius; whitelist mode with an empty list shows nothing | Implementation fact | `domain/plan.py`, `tests/test_plan.py` |
| 144 tests pass on macOS | Recorded live | `python3 -m pytest`, 2026-09-22 |
| Neither Windows module calls `WriteProcessMemory`, `CreateRemoteThread`, `SendInput`, `keybd_event`, `mouse_event`, `PostMessage` or `SetForegroundWindow` | Implementation fact | `tests/test_panel_contract.py` asserts the source |

## The overlay window

| Fact | Level | Source |
| --- | --- | --- |
| The overlay is created with `WS_EX_LAYERED \| WS_EX_TRANSPARENT \| WS_EX_TOPMOST \| WS_EX_TOOLWINDOW \| WS_EX_NOACTIVATE` and shown with `SW_SHOWNOACTIVATE` | Implementation fact | `ui/panel.py`, pinned by `tests/test_panel_contract.py` |
| The same window serves the in-game mode and the side-panel mode; only the anchoring rectangle differs | Implementation fact | `ui/layout.py` `place()`, `app.OverlayPresenter` |
| A client rectangle covering the whole monitor is reported as a fullscreen risk rather than classified, because a borderless window at monitor size is indistinguishable from a fullscreen swap chain by that measurement alone | Implementation fact | `services/window.py` `measure_window` |

### Verified on the game PC, 2026-09-22

The client was running **windowed at `1280x720`, at `(242,134)`**, class `UnityWndClass`,
title `Dead Frontier`, on a `1920x1080` primary screen.

| Fact | Level | Source |
| --- | --- | --- |
| The overlay appears over the game's own client area: it reports `visible=True at (256,148)-(686,388)`, which is the client origin `(242,134)` inset by the configured 14 px | Recorded live | `--presentation overlay --anchor top-left` job output; equals client + (14,14) |
| The readout is visible in a capture of the game's client area, above the game's rendering | Recorded live | `docs/evidence/2026-09-22-overlay-over-game-client.png` |
| The game's **own minimap read `1057 X 1017`** while the readout's header read `1057,1017` — the profiler's `gpscoords` and the client's displayed coordinate are the same number, which is the cross-check the whole coordinate decision rests on | Recorded live | the same capture, top-right of the client area |
| Clicks pass through: `WindowFromPoint` at the overlay's centre resolved to the window **underneath**, not to the overlay — and at the below-minimap placement it resolved to `UnityWndClass 'Dead Frontier'` itself, so a click in the readout reaches the game | Recorded live | `docs/evidence/2026-09-22-clickthrough-and-focus.txt` |
| The overlay does not take focus: the foreground window was the same `cmd.exe` before and after it appeared | Recorded live | same file |
| The created window really has `WS_EX_TRANSPARENT` and `WS_EX_NOACTIVATE` set, read back from Windows rather than assumed | Recorded live | same file |
| `GetClientRect` + `ClientToScreen` produce correct screen-space client rectangles on this machine: 9 decorated windows measured, every rectangle intersecting the screen plausibly, and the game's own `1280x720` at `(242,134)` | Recorded live | `docs/evidence/2026-09-22-window-probe.txt` |
| The font auto-pick resolved to **MS Gothic** there (MingLiU and SimSun are not installed on that machine) | Recorded live | the overlay's own `describe()` line |
| **F8 really registers as a global hotkey**: the overlay reports `F8 toggles whitelist mode` rather than the failure note, so the in-game whitelist toggle is live and not merely compiled in | Recorded live | `docs/evidence/2026-09-22-overlay-over-client-run.txt` |

### Verified on the game PC, 2026-09-22 (second session: the readout format)

| Fact | Level | Source |
| --- | --- | --- |
| The region minimap occupies client `(1060, 10)` size `215` at 1280x720 — measured, not assumed: the minimap's own `BUNKER` header sits at its top and its `1057 X 1017` readout at its bottom, bracketing the rectangle from both sides | Recorded live | client-area capture, cropped at that rectangle |
| The readout is placed **below the minimap, right-aligned to its right edge**: for a client at `(242,134)` it reports `(1177,363)-(1517,583)`, and `1517 = 242 + 1060 + 215` is the minimap's right edge while `363 = 134 + 10 + 215 + 4` is its bottom plus the gap | Recorded live | `docs/evidence/2026-09-22-overlay-below-minimap-run.txt` |
| The readout is visible under the minimap in a capture of the game's client area, bright green on the dark backing, with the game's own `1057 X 1017` just above it | Recorded live | `docs/evidence/2026-09-22-overlay-below-minimap-on-client.png` |
| The normal format renders exactly as asked: `6 x Bandits | 1054 x 1018 | 3LD1`, bright green, at the configured 12 px | Recorded live | same capture, and `…-formats.png` |
| The big/ultra format renders with the **end time**: `Charred Titan | 1046 x 1017 | 17:00` for a cycle that started at 16:00 and ends at 17:00 | Recorded live | `--big-boss "Charred Titan"` against the live 16:00 cycle |
| `5LD1` is the right encoding: the player at `1057,1017` and a boss at `1052,1018` is five blocks left and one down | Recorded live | the hand-written example, reproduced by the code and pinned by a test |
| Big/ultra bosses lead the list, so a special spawn is not buried under nearer ordinary ones | Implementation fact | `domain/plan.py`, `tests/test_view.py` |
| The settings window opens on the game PC: a visible `736x799` window titled `DFBossReminder settings` | Recorded live | `tools/pc/probe-config-gui.py` |
| **The built exes run**, not just the source: `Desktop\DFBossReminder.exe --once` prints the live plan, and `Desktop\DFBossReminderConfig.exe` opens its `736x799` window | Recorded live | `docs/evidence/2026-09-22-built-exe-once.txt`, `…-built-config-exe.txt` |
| The settings window needs no game: it was opened while the client was running, and the probe reports the client's state rather than requiring either answer | Recorded live | same probe |
| The overlay is refused when the game is not running, and the refusal is not swallowed by the console fallback | Implementation fact | `tests/test_app.py`, `app.GameNotRunning` |
| The tier is a **name list**, because the boss map carries no tier; the default is the wiki's Special Daily Bosses | Wiki-sourced | *Bosses*, threat levels 1–8 plus "Special Daily Bosses … extra tough … once per day … stay for 3 hours instead of the normal bosses' 1 hour" |

### Verified on the game PC, 2026-09-22 (third session: transparent 10 px)

| Fact | Level | Source |
| --- | --- | --- |
| The readout renders at 10 px in bright green with **no backing box**: the game's terrain shows through between and inside the glyphs | Recorded live | `docs/evidence/2026-09-22-overlay-transparent-on-client.png` |
| **GDI never writes the alpha byte**, so on a surface cleared to `alpha 0` the glyphs were drawn and then invisible — `UpdateLayeredWindow` composites by alpha. The fix gives every pixel we drew a full alpha, found by "cleared to zero, so any non-zero colour is ours" | Recorded live (found by it crashing the dump: `ValueError: bytes must be in range(0, 256)`) | `ui/panel.py` `_opaque_glyphs` |
| The window **sizes itself to its content**, so the notes at the bottom are no longer clipped; the height is a maximum, and anything over it is reported on the last line | Recorded live | `…-overlay-transparent-run.txt`; the earlier fixed height silently dropped the notes |
| The header, notes and status are Chinese by default and English with `--language en`; the boss lines are the fixed format in both | Recorded live + Implementation fact | the capture, and `tests/test_view.py` |
| **F8 is free on the game PC** (only F12 is held by something else), so the earlier "could NOT register F8" was two of this project's own overlays competing, not a conflict with another application | Recorded live | `tools/pc/probe-hotkeys.py`; the failure disappeared once the previous instance had exited |
| The toggle key is a setting, so a machine where it *is* taken can pick another | Implementation fact | `settings.hotkey`, `--hotkey` |
| **The frozen exe does not honour `PYTHONIOENCODING`**: the built executable wrote the console's own code page (Big5) even with the variable set to `utf-8`, so a redirected log was unreadable outside a Windows editor. The source run honoured it, so this is a property of the packaged build only | Recorded live | `Desktop\DFBossReminder.exe --once > e4.txt`, checked by byte inspection |
| Pinning the streams to UTF-8 is safe for a console as well: Windows writes to a console through `WriteConsoleW` (PEP 528), which takes UTF-16 and renders it with the console font, so the stream encoding only decodes this process's own bytes | Implementation fact | `app._make_streams_safe`; verified by the same run showing `20 格內` |

### Verified on the game PC, 2026-09-22 (fourth session: the client's own font)

| Fact | Level | Source |
| --- | --- | --- |
| The client's HUD font is **VIPER NORA** (Dimitris K., pOPdOG fONTS, 1999), and it is not installed on the machine - it is baked into the client's Unity assets | Recorded live | `sharedassets0.assets` contains the TTF's own `name` table: `'VIPER NORA'`, `'Dimitris K. - pOPdOG fONTS 1999'`, `'Macromedia Fontographer 4.1 23/3/1999'` |
| The TTF can be read out of that asset: a 480,148-byte font whose `name` table carries `VIPER NORA` | Recorded live | extracted at `0xc094b60` of a 206,883,260-byte asset |
| It renders as the game's own face: a sample line `+100% EXTRAORDINARY DAMAGE BOOST 194 / 400 (48%)` in the extracted font is indistinguishable from the game's HUD label of the same text | Recorded live | side-by-side in `docs/evidence/2026-09-22-overlay-game-font-on-client.png` |
| Loading it privately works and the face name is confirmed, not assumed: `AddFontResourceExW` returned 1 and GDI reported `VIPER NORA` for the requested face | Recorded live | the render probe; `FR_PRIVATE` means nothing is installed system-wide |
| The overlay uses it: `font=VIPER NORA, CJK MS Gothic; align=right; ... using the game's own font: VIPER NORA` | Recorded live | `docs/evidence/2026-09-22-overlay-game-font-run.txt` |
| **VIPER NORA has no CJK glyphs**, so the Chinese labels cannot be drawn in it - the header and notes would be a row of empty boxes beside boss lines that look perfect. Two faces are kept and each row picks by its content | Recorded live | the render probe drew 個附近 as boxes; the capture shows the Chinese rows in MS Gothic |
| The readout is right-aligned, so its rows share a right edge with the minimap | Recorded live | the same capture |

### Verified on the game PC, 2026-09-23 (seventh session: styles, one program, no following)

The player's four requests: drop the coordinate whitelist, add per-coordinate colours,
merge the settings window and the readout into one program with a start button, and stop
the overlay following the game window (it no longer worked) in favour of position buttons.

| Fact | Level | Source |
| --- | --- | --- |
| **Coordinate styles work as asked**: `red=1053,1019;1056,1016` painted those two rows red and `yellow=1058,1016;1058,1014` painted those two yellow, with every other row left green | Recorded live | `docs/evidence/2026-09-23-styles-red-yellow-surface.png` and `…-styles-run.txt` |
| A rule **never removes a row** (the difference from the whitelist it replaced), and the console reports `座標樣式 N 組，命中 M 列` so "why is it not red?" is answerable | Recorded live + Implementation fact | the same run; `tests/test_plan.py` |
| **The dump had been writing BMP rows as RGB** where the format is BGR, so every red in every piece of evidence this project produced came out blue. It was invisible for as long as the only colour in use was `#33FF33`, where red and blue are equal - the first red rule exposed it | Recorded live (found by looking at the picture, and confirmed by the pixel histogram) | `docs/evidence/2026-09-23-dump-channel-fix.png` shows the same surface before and after; `tests/test_panel_contract.py` pins the channel order |
| **One program**: the Desktop `DFBossReminder.exe`, launched with no arguments, opens the settings window (`DFBossReminder 設定`), and **開始** in that window starts the overlay **in the same process** | Recorded live | `docs/evidence/2026-09-23-settings-window-styles.bmp`; `…-config-gui-audit-live.txt`: `開始 (real controller): 運行中：overlay visible=True at (1246,359)-(1586,779)` |
| **停止 really stops it**: after 10 s the run reports `已停止`, `running=False`, and no overlay window is left behind | Recorded live | the same log |
| The four **position arrows** nudge the readout one step in the direction of the arrow, and the offset is stored so the next start uses it | Recorded live | `…-config-gui-audit.txt`: `the four arrows nudged: [('right', 5), ('left', 5), ('down', 5), ('up', 5)]`; `tests/test_layout.py` pins the sign for every anchor |
| The whole widget tree can be checked **without showing anybody a window**: the audit builds it withdrawn and reports `viewable=False` | Recorded live | `…-config-gui-audit.txt` |
| The **whitelist is gone** from the window and from the settings: `白名單` does not appear, and the audit fails if it comes back | Recorded live | the same audit, which checks for forbidden labels |
| The old `DFBossReminderConfig.exe` is **deleted by the build**, so there is one entry point and no stale second exe to double-click | Recorded live | `docs/evidence/2026-09-23-exe-build-styles.txt`; the Desktop holds only `DFBossReminder.exe` (11,131,174 bytes) |

### Verified on the game PC, 2026-09-23 (sixth session: the overlay is the boss list only)

The player asked for three changes: no header line in the overlay, nothing below the
boss rows in it, and a Traditional Chinese settings window.

| Fact | Level | Source |
| --- | --- | --- |
| The overlay over the client is **the boss rows and nothing else**: no `DFBossReminder … N 個附近` header, no waypoint line, no notes, no age | Recorded live | `docs/evidence/2026-09-23-overlay-bosses-only-on-client.png` — the minimap reads `1057 X 1017` with seven green rows under it and nothing else |
| The window also **reserves no band for a title**, so the first row starts two pixels from the top instead of leaving a strip of nothing | Recorded live | the 340×109 surface for seven rows in `…-overlay-bosses-only-surface.png`; `Overlay.title_band` |
| The **console keeps everything the overlay drops** — the header, the waypoint, the notes and the age — because it is now the only place that tells an empty list apart from a dead feed | Implementation fact | `view.console_lines`, pinned by a test that every overlay row appears in the console rendering |
| The **settings window is entirely Traditional Chinese** and renders it: no missing-glyph boxes, including the colour rows (`list（一般 boss）`) and the file path at the bottom | Recorded live | `docs/evidence/2026-09-23-settings-window-zh.png` (source run) and `…-settings-window-zh-from-exe.bmp` (the built exe) |
| Its buttons are **outside the scrolling area**, so 儲存 is reachable without scrolling; the window's initial height is read from the screen rather than assumed | Recorded live | the same captures; `config_gui.run_config` |
| **The F8 toggle had been dead code since `d409401`**: the registration sat after a `return` inside `_game_font_face`, so it never ran, while the ledger called the hotkey verified. It now registers at startup and the overlay reports it again | Recorded live | `F8 toggles whitelist mode` is back in the run's describe line (`…-overlay-bosses-only-run.txt`), and `tests/test_app.py` builds the presenter for real instead of through `__new__` |
| `PrintWindow` renders the Tk settings window faithfully with no activation, which is what makes the screenshot possible without taking the player's focus mid-fight | Recorded live | `tools/pc/capture-window.py`; the captures above came from it |
| Photographing the window **the moment its title appears catches it mid-build** — the bottom third was black, which reads as a layout bug rather than a race | Recorded live (found by looking at the picture) | the first capture of the taller window; the probe now lets it settle for two seconds |
| Killing the one-file exe's **parent** leaves the settings window running: every exe probe run left one open, and the next run found two windows titled the same | Recorded live | `matched hwnd=0x600702` and `matched hwnd=0x2e07cc` in the same run; `probe-config-gui.stop` now kills the tree with `taskkill /T` |

### Verified on the game PC, 2026-09-22 (fifth session: font weight and the shadow)

The player asked for `font-weight: 300`, and answering that honestly needed a
measurement rather than a read of the font's metadata. `tools/pc/probe-font-weight.py`
draws one identical line through the overlay's own drawing code, at seven weights and
three shadow styles, and compares the raw 32-bit surfaces.

| Fact | Level | Source |
| --- | --- | --- |
| The extracted font declares **one face**: `OS/2 usWeightClass 400`, `head macStyle 0`, `name[2] "Regular"` | Recorded live | read out of `~/.dfbossreminder/game-font.ttf` (480,148 bytes) |
| **Weights 100 through 500 draw byte-identical surfaces** — one MD5 and 2,562 ink pixels for all five, at every shadow style | Recorded live | `docs/evidence/2026-09-22-font-weight-probe.txt`; cross-checked independently by diffing the probe's dumped BMPs with Pillow, which finds no differing pixel |
| So `300` is **at the floor**, not "lighter than 400": it renders exactly the 400 raster, and asking for less buys nothing | Recorded live | the same probe |
| **From 700 GDI synthesises a heavier face** (2,680 ink pixels against 2,562), although the family has no bold: 700 and 900 are identical to each other and both differ from the 100–500 band | Recorded live | the same probe |
| GDI **echoes the requested weight back** through `GetObjectW` (`weight=300 (asked 300)`) even though the raster is the font's single face. The read-back is therefore reported as what was *recorded*, never as evidence of the drawn strokes | Recorded live | the probe's `asked` and `back` columns agree in all 21 rows |
| The four-offset shadow **put dark fringe on all four sides of every glyph**: 141 more pixels than a single offset at weight 300 (2,703 against 2,562 ink, 6% more ink) | Recorded live | the same probe |
| The lightening the player asked for is therefore real, and comes from the **single drop shadow** — the weight number provably changes nothing in that range | Recorded live | `docs/evidence/2026-09-22-overlay-weight-shadow-comparison.png`: the same text in the same font, `weight 400 + four offsets` above `weight 300 + one offset` |
| The readout over the client at the shipped settings: `font=VIPER NORA, CJK MS Gothic; weight=300 (asked 300); align=right; transparent backing (text only); text shadow on` | Recorded live | `docs/evidence/2026-09-22-overlay-weight300-run.txt` and `…-overlay-weight300-on-client.png` |

### Defects the live run found, and the fixes

Running it on Windows was worth it for these alone: none was visible from the
development machine or from any test.

| Defect | Cause | Fix |
| --- | --- | --- |
| The zh bearing words rendered as **blank boxes** | The font was `Consolas`, which has no CJK glyphs; GDI substitutes silently rather than failing | A candidate list of fixed-pitch CJK faces, each verified through `GetTextFaceW` before use |
| The **minutes column was cut off** (`0…`) | Columns were padded by `len()`, so a double-width `左` pushed the line past the panel and the ellipsis ate the last field | Padding by **display width** (`east_asian_width`), pinned by a test that every row is exactly 47 columns in both styles |
| The overlay died with `AttributeError: function 'GetTextFaceW' not found` | It was bound on `user32`; it lives in `gdi32` | Bound on `gdi32`, and any probe failure now means "face unavailable" so a missing glyph can never stop the readout appearing |
| A long joined name (`1 x Evolved Longarms + 1 x Irradiated …`) **elbowed the coordinate and the bearing off the line**, leaving `… \| …` | A fixed name budget, so the line overflowed the panel and the window's ellipsis ate the last fields | The budget is computed from the configured width and font size minus everything that follows the name; a test asserts every row fits the shipped width |
| The title was cut mid-word (`… 1057,1017  …`) | The title was one fixed string, wider than the narrow strip | The longest form that fits is used, dropping the account name first; a test checks the budget at every shipped width |
| The **notes at the bottom of the list were clipped** by a fixed window height — the worst thing to lose, because the notes are what says whether an empty readout is correct or a bug | A height chosen before the content was known | The window sizes itself to its content up to a configured maximum, and anything over that is reported on the last line rather than vanishing |
| With a transparent backing the **glyphs became invisible** | GDI does not write the alpha byte, so `alpha 0` pixels stayed `alpha 0` and `UpdateLayeredWindow` composited them away | The pixels this process drew are given a full alpha; the test is exact because the surface was cleared to zero first |
| A second overlay in one process **failed to open** with only `RegisterClassW failed: 1410` to show for it | The window class was named after `id(self) & 0xFFFF` — addresses are reused, so the name was not the unique identity it looked like — and `close()` never unregistered the class | The name is `DFBossReminderOverlay<pid>_<counter>`, which cannot repeat, and `close()` calls `UnregisterClassW`; both are pinned by tests. Found by the weight probe, which opens 21 overlays in one process and hit the collision on its eighth |

## Open questions

1. ~~Does the overlay appear over the client in windowed mode, above the game while
   the game is focused?~~ **Answered: yes** (table above). Borderless-windowed is
   still untested.
2. ~~Does the client rectangle place the overlay correctly under display DPI
   scaling?~~ **Answered: yes** on this machine at its current scaling (1920x1080,
   no scaling); a scaled display is still untested.
3. ~~Does a click over the overlay reach the game, and does the game keep focus?~~
   **Answered: yes for the click and for focus**, programmatically. Whether the game
   keeps *keyboard* focus while the user types is a human check.
4. **How often does the game report `gpscoords`?** Still unmeasured; the panel shows
   the age rather than assuming a cadence.
5. Does the boss map change shape between client updates in a way the parser has not
   seen? The parser skips what it cannot read and the fixtures use a real payload, so
   a change should appear as fewer bosses, not as a wrong block.
6. Does the overlay follow the client when the window is **moved**? The re-anchor runs
   every `watch_pid_seconds`, and the below-minimap corner is recomputed from the
   client each time, but no run has recorded a move.
7. **The refusal has never been seen live.** The client was running in every session
   and closing it would have cost the player their game, so "no game, no overlay" is
   unit-tested and pinned, not observed.
8. Does the settings window's **Save** round-trip through the real file on Windows?
   Its data half is tested and the window opens; no run has clicked Save.
9. Is `U`/`D` on the boss map the same way up as the client's own minimap? The
   encoding matches the player's example and the boss map's own orientation, but
   nobody has walked north and watched the field change.
10. ~~Is `font-weight: 300` actually drawing lighter text?~~ **Answered: 300 is the
   floor, not a lighter face** — 100 through 500 render byte-identically, and the
   lightening came from the single drop shadow (fifth session, above). What is still
   unmeasured is how the readout reads to the player's eye over busy terrain: ink and
   the capture are proxies, and no one has said "that looks right now".
