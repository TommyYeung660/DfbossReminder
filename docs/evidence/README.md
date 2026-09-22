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
| `2026-09-22-clickthrough-and-focus.txt` | `tools/pc/probe-clickthrough.py` output: `WS_EX_TRANSPARENT` and `WS_EX_NOACTIVATE` are really set, `WindowFromPoint` at the overlay's centre resolves to the window underneath, and the foreground window is unchanged |

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
