# Evidence

Records that back the claims in `docs/verified-facts.md`. A claim without a record
here is an implementation fact at best.

## What is in here

| File | What it shows |
| --- | --- |
| `2026-09-22-live-plan-radius6.json` | The plan for account `14008279` at block `1057,1017` with `--radius 6`: 5 bosses within the radius, 157 beyond it, and the leader `3 x Irradiated Titan` at `1058,1016`, distance 1, bearing `1右1上` |
| `2026-09-22-live-plan-whitelist.json` | The same account with whitelist mode on and one entry `1054,987:3=Bunker`: 159 of 162 sightings suppressed, three bosses shown at 28–32 blocks — outside the radius, which is the whitelist overriding it |
| `2026-09-22-overlay-surface.png` | The pixels the overlay itself handed to `UpdateLayeredWindow` on the game PC, with the zh bearing words rendering and the minutes column intact |
| `2026-09-22-overlay-over-game-client.png` | The game's client area (`1280x720` at `242,134`) photographed from the desktop while the overlay was up: the readout sits over the game, and the game's own minimap reads `1057 X 1017` — the same block the readout's header shows |
| `2026-09-22-window-probe.txt` | `tools/pc/probe-window.py` output: the client-rectangle measurement is correct on that display, and the game window is found at `1280x720` at `(242,134)` |
| `2026-09-22-overlay-game-font-on-client.png` | The readout in the client's own HUD font (VIPER NORA), right-aligned, with the game's `HEALTHY`/`NOURISHED` labels at the top in the same face for comparison; the Chinese rows are in the CJK fallback |
| `2026-09-22-overlay-game-font-right-aligned.png` | The same surface on its own |
| `2026-09-22-overlay-game-font-run.txt` | The run: `font=VIPER NORA, CJK MS Gothic; align=right`, `using the game's own font: VIPER NORA`, the placement, and the captures written |
| `2026-09-22-overlay-transparent-on-client.png` | The final readout: 10 px, bright green, **no backing box** — the game's terrain shows through — with the Chinese header and notes, and every note visible because the window sized itself to the content |
| `2026-09-22-overlay-transparent-10px-formats.png` | The same surface on its own, composited over mid-grey by the overlay itself |
| `2026-09-22-overlay-transparent-run.txt` | The run: the measured client rect, `transparent backing (text only); text shadow on`, `F8 toggles whitelist mode`, and the capture written |
| `2026-09-22-exe-build.txt` | `tools/pc/build-exe.cmd` building both exes onto the Desktop |
| `2026-09-22-built-exe-once.txt` | The built `DFBossReminder.exe` printing the live plan, so the packaged build works and not only the source |
| `2026-09-22-built-config-exe.txt` | The built `DFBossReminderConfig.exe` opening its settings window |
| `2026-09-22-overlay-below-minimap-on-client.png` | The final arrangement: the game's client area with its own minimap (`BUNKER`, `1057 X 1017`) at the top-right and the bright green boss list hanging directly below it — big bosses with their end time, ordinary ones with a compact bearing |
| `2026-09-22-overlay-below-minimap-formats.png` | The readout's own pixels at a readable size, showing both line formats (`Charred Titan \| 1048 x 1018 \| 17:00` and `3 x Mega Mother \| 1057 x 1016 \| U1`) |
| `2026-09-22-overlay-below-minimap-run.txt` | The whole run as the game PC printed it: the game window's rectangle, the readout's own `(1177,363)-(1517,583)`, the font, the hotkey, and both captures written |
| `2026-09-22-overlay-over-client-run.txt` | The whole in-game run as the game PC printed it: the client rectangle, `overlay visible=True at (256,148)-(686,388)`, `font=MS Gothic`, `F8 toggles whitelist mode`, and both captures written |
| `2026-09-22-exe-build-weight.txt` | `tools\pc\build-exe.cmd` rebuilding both Desktop exes with the weight and single-shadow change (`Built … DFBossReminder.exe (11116734 bytes, 22/09/2026 17:27)` and the config exe). It only worked after `stop-dfboss.ps1`: the previous exe was running and held the file |
| `2026-09-22-built-exe-weight.txt` | The rebuilt `DFBossReminder.exe` opened as an overlay and reported `weight=300 (asked 300); align=right; transparent backing (text only); text shadow on`, so the packaged build carries the change and not only the source |
| `2026-09-23-overlay-bosses-only-on-client.png` | The overlay over the game with the header, the waypoint and the notes removed: the client's own minimap reads `1057 X 1017` and seven green boss rows hang under it, with nothing above or below them |
| `2026-09-23-overlay-bosses-only-surface.png` | The same readout's own pixels: seven rows on a 340×109 surface, the first row two pixels from the top because no space is reserved for a title |
| `2026-09-23-overlay-bosses-only-2x.png` | The `--dump-frame` surface of the **built exe** at 2x, so the packaged build is what is being looked at |
| `2026-09-23-overlay-bosses-only-run.txt` | The run: the placement, `font=VIPER NORA, CJK MS Gothic; weight=300 (asked 300)`, and `F8 toggles whitelist mode` — the hotkey line that had been missing since `d409401` |
| `2026-09-23-console-keeps-the-notes.txt` | `--once` at the same moment: the same six boss rows **plus** the header, the waypoint line, `5 格內`, `半徑外 144 個` and `已更新 0 秒前`. This is the pair that shows the split — the overlay answers, the console explains |
| `2026-09-23-settings-window-zh.png` | The settings window in Traditional Chinese, photographed with `PrintWindow` (no activation, no focus stolen): 帳號與範圍, 白名單, 顯示外觀…
| `2026-09-23-settings-window-zh-from-exe.bmp` | The same window from the rebuilt `DFBossReminderConfig.exe`, so the frozen build renders the Chinese too and not only the source run |
| `2026-09-23-settings-window-zh.txt` | `tools/pc/probe-config-gui.py` output: it finds exactly one window titled `DFBossReminder 設定`, photographs it, reports whether the game happens to be running, and kills the process tree so nothing is left on the desktop |
| `2026-09-23-styles-red-yellow-surface.png` | The overlay's own pixels at 2x with two style rules on: `red=1053,1019;1056,1016` paints those two rows red, `yellow=1058,1016;1058,1014` paints those two yellow, everything else stays green. A style changes the colour and never removes the row |
| `2026-09-23-styles-run.txt` | The run that produced it: `--highlight "red=…" --highlight "yellow=…"`, the placement, and `fetched 15 boss events; player 1057,1017` |
| `2026-09-23-dump-channel-fix.png` | The same surface twice, before and after fixing the dump's channel order. Before: a red rule drawn blue and a yellow rule drawn cyan, because the rows were written as RGB into a format that is BGR. Invisible until the first non-green colour, since `#33FF33` has red equal to blue |
| `2026-09-23-config-gui-audit.txt` | `tools/pc/audit-config-gui.py`: the window built **withdrawn** (`viewable=False`), 100 labels, the styles table rendered 2 rows for 2 rules, 開始 reached the controller, the four arrows nudged in order, and no trace of the whitelist |
| `2026-09-23-config-gui-audit-live.txt` | The same audit with `--live`: 開始 with the **real** controller started the overlay in-process (`運行中：overlay visible=True at (1246,359)-(1586,779)`), it kept drawing for 10 s, and 停止 ended it (`已停止`, `running=False`) |
| `2026-09-23-settings-window-styles.bmp` | The built `DFBossReminder.exe` with no arguments: its settings window, photographed with `PrintWindow` — the 座標樣式 section, the 開始/停止 pair and the position arrows |
| `2026-09-23-exe-build-styles.txt` | `tools\pc\build-exe.cmd` building the single exe (`Built … DFBossReminder.exe (11131174 bytes, 23/09/2026 11:47)`) and removing the old `DFBossReminderConfig.exe` |
| `2026-09-23-exe-build-notitle.txt` | `tools\pc\build-exe.cmd` rebuilding both Desktop exes with these changes (`Built … DFBossReminder.exe (11118905 bytes, 23/09/2026 11:04)`) |
| `2026-09-22-clickthrough-and-focus.txt` | `tools/pc/probe-clickthrough.py` output: `WS_EX_TRANSPARENT` and `WS_EX_NOACTIVATE` are really set, `WindowFromPoint` at the overlay's centre resolves to the window underneath, and the foreground window is unchanged |
| `2026-09-22-font-weight-probe.txt` | `tools/pc/probe-font-weight.py` output: 21 surfaces for seven weights × three shadow styles. Weights 100–500 share one MD5 and one ink count, so a 300 request renders exactly the 400 raster; 700 and up make GDI synthesise a heavier face; the four-offset shadow adds 141 pixels of fringe over the single one |
| `2026-09-22-overlay-weight-shadow-comparison.png` | The same line in the same font twice, at 3x: `weight 300 asked, single drop shadow` above `weight 400 asked, four-offset shadow`. The shadow is the only difference between the rows, which is where the visible lightening comes from |
| `2026-09-22-overlay-weight300-on-client.png` | The readout over the game client at the shipped settings — `weight=300`, single drop shadow, right-aligned, transparent backing |
| `2026-09-22-overlay-weight300-run.txt` | The run that produced it: `font=VIPER NORA, CJK MS Gothic; weight=300 (asked 300); align=right; transparent backing (text only); text shadow on` |

The JSON plans were produced by the tool itself (`--once --json`); the probes wrote
their own output; the images came from the machine. None was written by hand.

## What is deliberately not here

* **No raw boss-map payloads.** `tests/fixtures/bossmap.json` and
  `tests/fixtures/profile.json` are trimmed copies of real responses with the
  timestamps shifted to a fixed instant in 2033, so the tests cannot rot. They are the
  parser's contract, and they live with the tests rather than here.
* **No recording of the game's keyboard focus while a person types.** The click and
  the foreground window are proven programmatically; keyboard focus under a human is
  not, and is listed as an open question rather than claimed.
