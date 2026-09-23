"""The settings window: this is the program's face, and it starts the readout.

The tool is one program. With no arguments it opens this window, and 開始 runs the
overlay in this same process - so there is no second program to find on the Desktop and
no question of which of two exes to double-click. The window is still perfectly usable
with the game closed: it is how the account id and the styles get set in the first place,
and 開始 says why it cannot start instead of failing silently.

Four things make it worth having its own window, rather than editing a JSON file or
remembering command-line flags:

* **coordinate styles** - the player's request was "1015,999 and 1020,998, when there is
  a boss, show it in red", which is a table of coordinates and colours;
* **the position buttons** - where the readout sits is tuned by looking at the game, and
  a nudge that needs a restart before you can see it is a nudge you cannot aim;
* **the font size and the colours** - the same reason: judged by looking at the game;
* **the big-boss names** - the one part of the tier rule the data does not carry, so the
  player must be able to write the list.

The value-building and validation are plain functions (``form_from_settings``,
``payload_from_form``, ``normalized``) so the rules can be tested without a display. Only
:func:`run_config` needs tkinter, and starting the readout is delegated to whatever
controller is handed in, so this module never needs to know about presenters or threads.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.bosses import DEFAULT_BIG_BOSSES
from ..domain.colours import normalize_colour
from ..domain.coordinates import CoordinateError, parse_cells
from ..domain.coordinates import to_dict as cells_to_dict
from ..domain.styles import StyleError, parse_highlights
from ..domain.settings import (
    ANCHORS,
    COLOUR_KEYS,
    DEFAULT_COLOURS,
    DIRECTION_STYLES,
    LANGUAGES,
    PRESENTATIONS,
    Settings,
    parse_settings,
    to_dict,
)

# The window is in Traditional Chinese, like the readout's own labels, because the person
# who asked for the tool reads Chinese. The identifiers the settings file and the command
# line use are left alone - ``below-minimap`` and ``console`` stay as they are - so the
# window and the flags keep naming the same thing.
COLOUR_LABELS = {
    "list": "一般 boss",
    "big": "大型 boss",
    "title": "標題",
    "note": "附註",
    "background": "背景",
    "border": "邊框",
}

# How far one press of a position button moves the readout, in pixels. Small enough to
# place it exactly, large enough not to need twenty presses.
NUDGE_STEP = 5


def form_from_settings(settings: Settings) -> dict:
    """The plain values the widgets are filled from.

    Kept as plain data - strings, ints, lists - because that is what a widget holds,
    and keeping it separate from the widget code is what lets the round trip be
    tested without opening a window.
    """
    return {
        "user_id": settings.user_id,
        "radius_blocks": settings.radius_blocks,
        "include_missions": settings.include_missions,
        "show_all_without_player": settings.show_all_without_player,
        "highlights": [
            # One rule per row: the colour and the cells it covers, as the player typed
            # them. The text form is what the window edits because that is also what
            # ``--highlight`` takes, so the window and the flag cannot drift.
            {"colour": highlight.colour,
             "cells": ";".join(cell.describe() for cell in highlight.cells)}
            for highlight in settings.highlights
        ],
        "font_size": settings.font_size,
        "font_weight": settings.font_weight,
        "font_face": settings.font_face,
        "opacity": settings.opacity,
        "text_shadow": settings.text_shadow,
        "language": settings.language,
        "colours": settings.colour_map,
        "width": settings.width,
        "height": settings.height,
        "max_rows": settings.max_rows,
        "presentation": settings.presentation,
        "anchor": settings.anchor,
        "offset_x": settings.offset_x,
        "offset_y": settings.offset_y,
        "minimap_left": settings.minimap_left,
        "minimap_top": settings.minimap_top,
        "minimap_size": settings.minimap_size,
        "minimap_gap": settings.minimap_gap,
        "direction_style": settings.direction_style,
        "poll_seconds": settings.poll_seconds,
        "stale_seconds": settings.stale_seconds,
        "big_bosses": "\n".join(settings.big_bosses),
        "base_url": settings.base_url,
        "waypoints": [
            {"label": label, "x": block.x, "y": block.y} for label, block in settings.waypoints
        ],
    }


def _int(value: object, default: int = 0) -> int:
    """A widget's text as an int, with the default when it is not one.

    Returning the default rather than raising keeps one bad cell from blocking a save
    of everything else; ``normalized`` then reports the difference.
    """
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _float(value: object, default: float = 0.0) -> float:
    if isinstance(value, float):
        return value
    if isinstance(value, (int, str)):
        try:
            return float(str(value).strip())
        except ValueError:
            return default
    return default


def payload_from_form(form: dict) -> dict:
    """Turn the widget values into the JSON-shaped payload ``parse_settings`` reads.

    The shapes match ``to_dict`` on purpose, so a form saved and reloaded is the same
    settings, and so :func:`normalized` can compare them key by key. That is also why a
    style rule's cells are parsed here rather than left as the typed text: the file stores
    them parsed, and "you typed text, we store data" would otherwise be reported to the
    player as a change the tool made.
    """
    highlights = []
    for row in form.get("highlights") or []:
        colour = str(row.get("colour", "")).strip()
        cells = str(row.get("cells", "")).strip()
        if not colour or not cells:
            continue          # a half-filled rule is dropped, not saved as invisible
        try:
            parsed = cells_to_dict(parse_cells(cells))
        except CoordinateError:
            # Kept as typed, so the difference shows up in ``normalized``'s notes rather
            # than being silently dropped. ``do_save`` refuses first and names the rule.
            parsed = cells
        highlights.append({"colour": normalize_colour(colour) or colour, "cells": parsed})
    big_bosses = [line.strip() for line in str(form.get("big_bosses", "")).splitlines()
                  if line.strip()]
    return {
        "user_id": str(form.get("user_id", "")).strip(),
        "radius_blocks": _int(form.get("radius_blocks"), 8),
        "include_missions": bool(form.get("include_missions")),
        "show_all_without_player": bool(form.get("show_all_without_player")),
        "highlights": highlights,
        "font_size": _int(form.get("font_size"), 10),
        "font_weight": _int(form.get("font_weight"), 300),
        "font_face": str(form.get("font_face", "")).strip(),
        "opacity": _float(form.get("opacity"), 0.0),
        "text_shadow": bool(form.get("text_shadow")),
        "language": form.get("language"),
        "colours": dict(form.get("colours") or {}),
        "width": _int(form.get("width"), 300),
        "height": _int(form.get("height"), 220),
        "max_rows": _int(form.get("max_rows"), 12),
        "presentation": form.get("presentation"),
        "anchor": form.get("anchor"),
        "offset_x": _int(form.get("offset_x"), 14),
        "offset_y": _int(form.get("offset_y"), 14),
        "minimap_left": _int(form.get("minimap_left"), 1060),
        "minimap_top": _int(form.get("minimap_top"), 10),
        "minimap_size": _int(form.get("minimap_size"), 215),
        "minimap_gap": _int(form.get("minimap_gap"), 4),
        "direction_style": form.get("direction_style"),
        "poll_seconds": _float(form.get("poll_seconds"), 20.0),
        "stale_seconds": _float(form.get("stale_seconds"), 120.0),
        "big_bosses": big_bosses,
        "base_url": str(form.get("base_url", "")).strip(),
        "waypoints": form.get("waypoints") or [],
    }


def normalized(payload: dict) -> tuple[Settings, list[str]]:
    """Validate a payload, and say which fields the tool had to change.

    Without this the window would be able to accept ``radius = 9999`` and quietly
    store 200, which is the kind of silent correction that makes a settings file
    untrustworthy.
    """
    settings = parse_settings(payload)
    stored = to_dict(settings)
    notes = [f"{key}: {value!r} -> {stored[key]!r}"
             for key, value in payload.items()
             if key in stored and stored[key] != value]
    return settings, notes


def run_config(path: Path, load, save, controller=None, visible: bool = True,
               log=print) -> int:  # noqa: ANN001
    """Open the settings window and run its event loop.

    ``load`` and ``save`` are injected so the window can be driven from a test with a
    temporary file, and so this module has no opinion about where settings live.

    ``controller`` is whatever can start, stop and nudge the readout - ``app`` passes its
    :class:`~dfbossreminder.app.OverlayController`, a test passes a stub. With none, the
    開始 and 停止 buttons say so instead of failing; the window is still a working settings
    editor, which is what a machine without a game can use.

    ``visible=False`` builds the whole window and never shows it. That is for the audit
    tool on the game PC, and it exists because of a mistake worth recording: a test that
    *opened* the window to check it put a dozen settings windows on the developer's screen
    while the suite ran. Verifying a window is worth doing, but not by interrupting
    whoever is sitting at the machine - and the machine that matters is the Windows one
    anyway, which is what ``tools/pc/audit-config-gui.py`` is for.

    Returns 0 when the window is closed, 1 when tkinter is unavailable (a Python
    without it is a real install) - the message says which.

    Every label is Traditional Chinese. The values the settings file and the command line
    use are not translated: a combobox still shows ``below-minimap``, because that is the
    word the flags and the docs use for the same thing.
    """
    try:
        import tkinter as tk
        from tkinter import colorchooser, messagebox, ttk
    except ImportError as error:                     # pragma: no cover - needs a display
        log(f"這個 Python 沒有 tkinter，所以設定視窗開不起來（{error}）。\n"
            f"請直接編輯 {path}，或改用命令列選項。")
        return 1

    settings = load()

    root = tk.Tk()
    if not visible:
        # Withdrawn before anything is built, so an audit run never puts a window in front
        # of whoever is using the machine.
        root.withdraw()
    root.title("DFBossReminder 設定")
    # Tall enough to show the buttons without scrolling, but never taller than the screen:
    # the window has a scrollbar, and one that opens taller than the display is worse than
    # one that needs a scroll. The screen is asked, not assumed - the game PC is 1080 high
    # and the machine it gets developed on is not.
    root.update_idletasks()
    height = max(560, min(940, root.winfo_screenheight() - 90))
    root.geometry(f"780x{height}")
    root.minsize(680, 560)

    # Packed before the canvas: the canvas expands to fill, so anything packed after
    # it gets no space at all and the status line would never be visible.
    status = ttk.Label(root, text=f"設定檔：{path}", foreground="#444444")
    status.pack(side="bottom", fill="x", padx=12, pady=6)

    # The buttons live outside the scrolling area, for the same reason: the form is taller
    # than any screen, and an action you have to scroll to find reads as a missing one.
    # The frame is packed here and filled in below, where the callbacks exist.
    actions = ttk.Frame(root, padding=(12, 6))
    actions.pack(side="bottom", fill="x")

    canvas = tk.Canvas(root, highlightthickness=0)
    scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
    body = ttk.Frame(canvas, padding=12)
    body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=body, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    variables: dict[str, object] = {}
    style_rows: list[dict] = []

    def section(text: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(body, text=text, padding=8)
        frame.pack(fill="x", pady=(0, 10))
        return frame

    def entry(parent, label: str, key: str, width: int = 10, value=None) -> None:  # noqa: ANN001
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=24).pack(side="left")
        variable = tk.StringVar(value=str(value if value is not None else ""))
        variables[key] = variable
        ttk.Entry(row, textvariable=variable, width=width).pack(side="left")

    def check(parent, label: str, key: str, value: bool) -> None:  # noqa: ANN001
        variable = tk.BooleanVar(value=bool(value))
        variables[key] = variable
        ttk.Checkbutton(parent, text=label, variable=variable).pack(anchor="w")

    def choice(parent, label: str, key: str, options: tuple[str, ...], value: str) -> None:  # noqa: ANN001
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text=label, width=24).pack(side="left")
        variable = tk.StringVar(value=value)
        variables[key] = variable
        ttk.Combobox(row, textvariable=variable, values=list(options),
                     state="readonly", width=18).pack(side="left")

    # ---------------------------------------------------------------- account
    account = section("帳號與範圍")
    entry(account, "Dead Frontier 使用者 ID", "user_id", value=settings.user_id)
    entry(account, "附近半徑（格）", "radius_blocks", value=settings.radius_blocks)
    entry(account, "Boss 地圖網址", "base_url", width=34, value=settings.base_url)
    entry(account, "更新間隔（秒）", "poll_seconds", value=settings.poll_seconds)
    entry(account, "幾秒後視為過期", "stale_seconds", value=settings.stale_seconds)
    check(account, "同時顯示任務生成的 boss", "include_missions", settings.include_missions)
    check(account, "位置不明時列出所有 boss",
          "show_all_without_player", settings.show_all_without_player)

    # ---------------------------------------------------------------- placement
    placement = section("顯示位置")
    choice(placement, "顯示方式", "presentation", PRESENTATIONS, settings.presentation)
    choice(placement, "對齊位置", "anchor", ANCHORS, settings.anchor)
    entry(placement, "對齊位移 x", "offset_x", value=settings.offset_x)
    entry(placement, "對齊位移 y", "offset_y", value=settings.offset_y)

    # Near the top on purpose: this is the section the player touches while the game is
    # running - moving the readout out of the way or back into place - and the form is
    # taller than the screen, so anything below the fold needs scrolling to reach.
    #
    # The readout no longer follows the game window (it moved under the player while
    # they were reading it, and they asked for that to go). The arrows act on a running
    # readout at once as a live adjustment, and 重新校正位置 drops that adjustment and
    # re-reads this section - which is also what makes a game window that has *moved*
    # recoverable without stopping and starting the overlay.
    nudge = ttk.LabelFrame(placement, text="位置微調", padding=8)
    nudge.pack(fill="x", pady=(8, 0))
    arrow_row = ttk.Frame(nudge)
    arrow_row.pack(anchor="w")
    step_var = tk.StringVar(value=str(NUDGE_STEP))
    ttk.Label(arrow_row, text="每按一次（px）").pack(side="left")
    ttk.Entry(arrow_row, textvariable=step_var, width=5).pack(side="left", padx=4)
    for label, direction in (("←", "left"), ("→", "right"), ("↑", "up"), ("↓", "down")):
        ttk.Button(arrow_row, text=label, width=3,
                   command=lambda d=direction: do_nudge(d)).pack(side="left", padx=1)
    # The callbacks are defined further down, with the rest of the actions, so these
    # buttons call them through a lambda - the name is looked up when the button is
    # pressed, which is also how the arrows above work.
    ttk.Button(arrow_row, text="重新校正位置",
               command=lambda: do_realign()).pack(side="left", padx=(10, 0))
    ttk.Label(nudge, text="箭頭按一下移一步，只是臨時微調，不會存進設定；"
                          "overlay 正在跑時會立刻看到。\n"
                          "「重新校正位置」把微調歸零，回到上面「對齊位置／對齊位移」"
                          "設定的位置 —— 遊戲視窗移動過之後也按它。",
              foreground="#666666", justify="left").pack(anchor="w", pady=(4, 0))

    ttk.Label(placement, text="below-minimap 用小地圖的矩形，座標是客戶區座標：").pack(
        anchor="w", pady=(6, 0))
    entry(placement, "小地圖 left", "minimap_left", value=settings.minimap_left)
    entry(placement, "小地圖 top", "minimap_top", value=settings.minimap_top)
    entry(placement, "小地圖 size", "minimap_size", value=settings.minimap_size)
    entry(placement, "小地圖下方間距", "minimap_gap", value=settings.minimap_gap)

    # ------------------------------------------------------- coordinate styles
    styles = section("座標樣式（命中的 boss 用這個顏色顯示）")
    ttk.Label(styles, text="座標      顏色        （1015,999 或 1015,999:2 表示連周圍兩格）",
              font=("Consolas", 9)).pack(anchor="w")
    table = ttk.Frame(styles)
    table.pack(fill="x")

    def add_style_row(data: dict | None = None) -> None:
        data = data or {"colour": "red", "cells": ""}
        line = ttk.Frame(table)
        line.pack(fill="x", pady=1)
        cells = tk.StringVar(value=str(data.get("cells", "")))
        colour = tk.StringVar(value=str(data.get("colour", "red")))
        ttk.Entry(line, textvariable=cells, width=30).pack(side="left", padx=1)

        def pick() -> None:
            _rgb, chosen = colorchooser.askcolor(
                color=normalize_colour(colour.get()) or "#FF3333", title="這個樣式的顏色")
            if chosen:
                colour.set(chosen.upper())

        swatch = tk.Label(line, textvariable=colour, width=10)
        swatch.pack(side="left", padx=4)

        def repaint(*_args) -> None:  # noqa: ANN002
            # The swatch is the colour name as well as the colour, so a name that is not
            # a colour shows up as grey with the name still readable instead of silently
            # becoming the wrong shade.
            shown = normalize_colour(colour.get())
            swatch.configure(background=shown or "#DDDDDD",
                             foreground="#111111" if shown else "#990000")

        colour.trace_add("write", repaint)
        repaint()
        ttk.Button(line, text="選色", width=6, command=pick).pack(side="left", padx=2)
        ttk.Button(line, text="顏色名", width=8,
                   command=lambda: colour.set("red")).pack(side="left", padx=2)

        def remove() -> None:
            style_rows.remove(row_record)
            line.destroy()

        row_record = {"cells": cells, "colour": colour, "frame": line}
        style_rows.append(row_record)
        ttk.Button(line, text="移除", width=6, command=remove).pack(side="left", padx=4)

    for existing in form_from_settings(settings)["highlights"]:
        add_style_row(existing)
    ttk.Button(styles, text="新增樣式", command=add_style_row).pack(anchor="w", pady=4)
    ttk.Label(styles, text="顏色可寫 red、orange、yellow、green、cyan、blue、purple、pink、"
                           "white，或 #RRGGBB。多組座標用「;」分隔。\n"
                           "樣式只改顏色，不會把其他 boss 藏起來；同一格有多條規則時，"
                           "以最上面那條為準。",
              foreground="#666666", justify="left").pack(anchor="w")

    # ------------------------------------------------------------- appearance
    appearance = section("顯示外觀")
    entry(appearance, "字體大小（px）", "font_size", value=settings.font_size)
    entry(appearance, "字體粗細（100-900）", "font_weight", value=settings.font_weight)
    entry(appearance, "字體（留空＝自動選擇）", "font_face", width=24,
          value=settings.font_face)
    entry(appearance, "背景不透明度（0＝全透明）", "opacity", value=settings.opacity)
    check(appearance, "文字加深色陰影（透明底時使用）",
          "text_shadow", settings.text_shadow)
    choice(appearance, "標籤語言", "language", LANGUAGES, settings.language)
    entry(appearance, "寬度（px）", "width", value=settings.width)
    entry(appearance, "高度（px，最大值）", "height", value=settings.height)
    entry(appearance, "最多列數", "max_rows", value=settings.max_rows)
    choice(appearance, "主控台方位用詞", "direction_style", DIRECTION_STYLES,
           settings.direction_style)

    colours_frame = ttk.Frame(appearance)
    colours_frame.pack(fill="x", pady=(6, 0))
    colour_vars = dict(settings.colour_map)

    def pick_colour(key: str, swatch: tk.Label) -> None:
        _rgb, chosen = colorchooser.askcolor(
            color=colour_vars.get(key, "#FFFFFF"),
            title=f"選擇顏色：{key}（{COLOUR_LABELS.get(key, key)}）")
        if chosen:
            colour_vars[key] = chosen.upper()
            swatch.configure(background=colour_vars[key], text=colour_vars[key])

    for key in COLOUR_KEYS:
        line = ttk.Frame(colours_frame)
        line.pack(fill="x", pady=1)
        ttk.Label(line, text=f"{key}（{COLOUR_LABELS.get(key, key)}）",
                  width=20).pack(side="left")
        swatch = tk.Label(line, text=colour_vars.get(key, DEFAULT_COLOURS.get(key, "#FFFFFF")),
                          background=colour_vars.get(key, DEFAULT_COLOURS.get(key, "#FFFFFF")),
                          width=12)
        swatch.pack(side="left", padx=4)
        ttk.Button(line, text="選擇", width=9,
                   command=lambda k=key, s=swatch: pick_colour(k, s)).pack(side="left")

    # ------------------------------------------------------------- big bosses
    big = section("大型／終極 boss（顯示結束時間）")
    ttk.Label(big, text="一行一個名稱。boss 地圖沒有分級欄位，所以由這份清單決定\n"
                        "哪些 boss 用結束時間的格式顯示。",
              justify="left").pack(anchor="w")
    big_box = tk.Text(big, height=6, width=40)
    big_box.insert("1.0", "\n".join(settings.big_bosses or DEFAULT_BIG_BOSSES))
    big_box.pack(fill="x", pady=4)

    # ---------------------------------------------------------------- actions
    def collect() -> dict:
        """The current widget values, in the plain shape ``payload_from_form`` reads."""
        form = {key: variable.get() for key, variable in variables.items()}
        form["colours"] = dict(colour_vars)
        form["big_bosses"] = big_box.get("1.0", "end")
        form["highlights"] = [{"colour": record["colour"].get(), "cells": record["cells"].get()}
                              for record in style_rows]
        form["waypoints"] = [{"label": label, "x": block.x, "y": block.y}
                             for label, block in settings.waypoints]
        return form

    def current() -> tuple[Settings, list[str]]:
        """What the form says right now, through the same validation a save uses."""
        return normalized(payload_from_form(collect()))

    def do_nudge(direction: str) -> None:
        """Move the readout one step, as a live adjustment of the configured position.

        It works on a running overlay only, and it is **not saved**: 顯示位置 holds the
        position the player configured, so 重新校正位置 can always put the readout back
        there. Saving the arrows into 對齊位移 - which this did first - made that button do
        nothing, because the "configured" position moved with every press.
        """
        if controller is None:
            return
        try:
            step = max(1, min(200, int(step_var.get().strip())))
        except ValueError:
            step = NUDGE_STEP
            step_var.set(str(NUDGE_STEP))
        settings_now, _notes = current()
        message = controller.nudge(settings_now, direction, step)
        if not controller.running():
            message += "（overlay 沒在跑，開始後才會看到）"
        status.configure(text=message)

    def style_problem() -> str:
        """The first style rule the tool cannot read, or an empty string.

        The rules are validated before anything is saved, and a problem *refuses the
        save*: storing something other than what the player typed - or storing nothing
        because one cell has a typo - is the silent correction this window exists to
        avoid. The message names the rule, so it can be found in the table.
        """
        rules = payload_from_form(collect())["highlights"]
        try:
            parse_highlights(rules)
        except StyleError as error:
            return str(error)
        for rule in rules:
            try:
                parse_cells(rule["cells"])
            except CoordinateError as error:
                return str(error)
        return ""

    def do_save() -> None:
        problem = style_problem()
        if problem:
            messagebox.showerror("DFBossReminder", f"座標樣式有問題，尚未儲存：\n\n{problem}")
            return
        payload = payload_from_form(collect())
        new_settings, notes = normalized(payload)
        try:
            save(new_settings)
        except OSError as error:
            messagebox.showerror("DFBossReminder", f"無法儲存：\n{error}")
            return
        message = f"已儲存至 {path}"
        if notes:
            message += "\n\n儲存前已調整：\n  " + "\n  ".join(notes)
        if new_settings.user_id != payload["user_id"]:
            message += ("\n\n注意：使用者 ID 必須是數字（例如 14008279），"
                        "已保留先前有效的值。")
        status.configure(text=message.splitlines()[0])
        messagebox.showinfo("DFBossReminder", message)

    def do_reload() -> None:
        if not messagebox.askyesno("DFBossReminder", "要從檔案重新載入，放棄目前的修改嗎？"):
            return
        fresh = form_from_settings(load())
        for key, value in fresh.items():
            if key in variables and not isinstance(variables[key], tk.BooleanVar):
                variables[key].set(str(value))
            elif key in variables:
                variables[key].set(bool(value))
        colour_vars.clear()
        colour_vars.update(fresh["colours"])
        for record in list(style_rows):
            record["frame"].destroy()
        style_rows.clear()
        for existing in fresh["highlights"]:
            add_style_row(existing)
        big_box.delete("1.0", "end")
        big_box.insert("1.0", fresh["big_bosses"])
        status.configure(text=f"已從 {path} 重新載入")

    def do_realign() -> None:
        """Put the readout back where 顯示位置 says: drop the arrows' adjustment, re-read.

        The replacement for the deleted auto-follow: the overlay no longer re-anchors
        itself when the game window moves, so this is the button that makes a moved window
        recoverable, and the one that undoes the position arrows. It also applies an edited
        anchor or minimap rectangle without a restart, because it saves the form first and
        hands those settings to the running readout.
        """
        if controller is None:
            return
        problem = style_problem()
        if problem:
            messagebox.showerror("DFBossReminder", f"座標樣式有問題，尚未儲存：\n\n{problem}")
            return
        settings_now, _notes = current()
        try:
            save(settings_now)
        except OSError as error:
            status.configure(text=f"重新校正了，但存不進設定檔：{error}")
            return
        _ok, message = controller.realign(settings_now)
        status.configure(text=message)
        refresh_buttons()

    def refresh_buttons() -> None:
        """The start/stop pair follows whether the readout is really running.

        Read from the controller rather than remembered from the last press: an overlay
        that stopped because it crashed, or one that was started before this window was
        opened, would leave the pair lying about it.
        """
        if controller is None:
            start_button.state(["disabled"])
            stop_button.state(["disabled"])
            return
        live = controller.running()
        start_button.state(["disabled"] if live else ["!disabled"])
        stop_button.state(["!disabled"] if live else ["disabled"])

    def do_start() -> None:
        """Save what the form says, then run the readout from it."""
        if controller is None:
            messagebox.showinfo("DFBossReminder", "這個版本沒有啟動 overlay 的功能。")
            return
        problem = style_problem()
        if problem:
            messagebox.showerror("DFBossReminder", f"座標樣式有問題，無法開始：\n\n{problem}")
            return
        settings_now, _notes = current()
        if not settings_now.user_id:
            messagebox.showinfo("DFBossReminder", "請先填 Dead Frontier 使用者 ID。")
            return
        try:
            save(settings_now)
        except OSError as error:
            messagebox.showerror("DFBossReminder", f"無法儲存：\n{error}")
            return
        ok, message = controller.start(settings_now)
        status.configure(text=message)
        refresh_buttons()
        if not ok:
            # The refusal is a sentence, not a traceback: "the game is not running" is
            # the most likely answer, and it has to read as an instruction.
            messagebox.showinfo("DFBossReminder", message)

    def do_stop() -> None:
        if controller is None:
            return
        status.configure(text=controller.stop())
        refresh_buttons()

    def on_close() -> None:
        # One program, one lifetime: closing the window stops the readout it started,
        # because the readout lives in this process and would die with it anyway. Saying
        # so is better than a window that closes and leaves nothing behind.
        if controller is not None and controller.running():
            controller.stop()
        root.destroy()

    start_button = ttk.Button(actions, text="開始", command=do_start)
    start_button.pack(side="left")
    stop_button = ttk.Button(actions, text="停止", command=do_stop, state="disabled")
    stop_button.pack(side="left", padx=6)
    refresh_buttons()
    ttk.Separator(actions, orient="vertical").pack(side="left", fill="y", padx=8)
    ttk.Button(actions, text="儲存", command=do_save).pack(side="left")
    ttk.Button(actions, text="重新載入", command=do_reload).pack(side="left", padx=8)
    ttk.Button(actions, text="關閉", command=on_close).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", on_close)
    ttk.Label(actions, text="（關閉視窗會一併停止 overlay）",
              foreground="#666666").pack(side="left")

    root.mainloop()
    return 0


def describe_round_trip(settings: Settings) -> dict:
    """A small self-check: the form of these settings, and back, must not change them.

    Used by the tests, and printed by ``--show-config`` when asked, because a settings
    window that cannot round-trip its own file is worse than no window.
    """
    form = form_from_settings(settings)
    payload = payload_from_form(form)
    back, notes = normalized(payload)
    return {"form": form, "payload": payload, "settings": to_dict(back), "notes": notes,
            "stable": back == settings}


