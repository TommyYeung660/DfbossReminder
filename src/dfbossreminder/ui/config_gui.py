"""The settings window: the whitelist, and how the readout looks.

Requirement: an independent configuration interface, rather than editing a JSON file
or remembering command-line flags. Three things make it worth having its own window:

* **the whitelist** is a list of coordinates, which is awkward to keep retyping on a
  command line and easy to get wrong in a file;
* **the font size and the colours** are things you tune by looking at the game, so
  they need to be changeable while the game is up;
* **the big-boss names** are the one part of the tier rule the data does not carry,
  so the player must be able to write the list.

The window is deliberately independent of the overlay: it does not need the game to
be running, it does not create an overlay, and it writes the same settings file the
overlay reads.

The value-building and validation are plain functions (``form_from_settings``,
``payload_from_form``, ``normalized``) so the rules can be tested without a display;
only :func:`run_config` needs tkinter.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.bosses import DEFAULT_BIG_BOSSES
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

# A whitelist entry's radius, in blocks. Bounded because a radius of 500 watches the
# whole map and is far more likely to be a typo than an intention.
MAX_RADIUS = 40


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
        "whitelist_mode": settings.whitelist_mode,
        "whitelist": [
            {"x": entry.block.x, "y": entry.block.y, "radius": entry.radius, "label": entry.label}
            for entry in settings.whitelist
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
    settings, and so :func:`normalized` can compare them key by key.
    """
    whitelist = []
    for index, row in enumerate(form.get("whitelist") or []):
        x, y = _int(row.get("x"), 1 << 30), _int(row.get("y"), 1 << 30)
        if x == 1 << 30 or y == 1 << 30:
            continue          # a half-typed row is dropped, not saved as 0,0
        whitelist.append({
            "x": x,
            "y": y,
            "radius": max(0, min(MAX_RADIUS, _int(row.get("radius"), 0))),
            "label": str(row.get("label", "")).strip(),
        })
    big_bosses = [line.strip() for line in str(form.get("big_bosses", "")).splitlines()
                  if line.strip()]
    return {
        "user_id": str(form.get("user_id", "")).strip(),
        "radius_blocks": _int(form.get("radius_blocks"), 8),
        "include_missions": bool(form.get("include_missions")),
        "show_all_without_player": bool(form.get("show_all_without_player")),
        "whitelist_mode": bool(form.get("whitelist_mode")),
        "whitelist": whitelist,
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


def run_config(path: Path, load, save, log=print) -> int:  # noqa: ANN001
    """Open the settings window and run its event loop.

    ``load`` and ``save`` are injected so the window can be driven from a test with a
    temporary file, and so this module has no opinion about where settings live.

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
    whitelist_rows: list[dict] = []

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

    # -------------------------------------------------------------- whitelist
    whitelist = section("白名單")
    check(whitelist, "白名單模式：只顯示這些座標",
          "whitelist_mode", settings.whitelist_mode)
    ttk.Label(whitelist, text="x        y       半徑     標籤           ",
              font=("Consolas", 9)).pack(anchor="w")
    table = ttk.Frame(whitelist)
    table.pack(fill="x")

    def add_whitelist_row(data: dict | None = None) -> None:
        data = data or {"x": 0, "y": 0, "radius": 0, "label": ""}
        line = ttk.Frame(table)
        line.pack(fill="x", pady=1)
        cells = {}
        for key, width in (("x", 7), ("y", 7), ("radius", 6), ("label", 16)):
            variable = tk.StringVar(value=str(data.get(key, "")))
            cells[key] = variable
            ttk.Entry(line, textvariable=variable, width=width).pack(side="left", padx=1)

        def remove() -> None:
            whitelist_rows.remove(row_record)
            line.destroy()

        row_record = {"cells": cells, "frame": line}
        whitelist_rows.append(row_record)
        ttk.Button(line, text="移除", width=8, command=remove).pack(side="left", padx=4)

    for existing in form_from_settings(settings)["whitelist"]:
        add_whitelist_row(existing)
    ttk.Button(whitelist, text="新增座標", command=add_whitelist_row).pack(anchor="w", pady=4)
    ttk.Label(whitelist, text="半徑 0 只監看那一格；半徑 2 連周圍兩格一起監看。",
              foreground="#666666").pack(anchor="w")

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

    # ---------------------------------------------------------------- placement
    placement = section("顯示位置")
    choice(placement, "顯示方式", "presentation", PRESENTATIONS, settings.presentation)
    choice(placement, "對齊位置", "anchor", ANCHORS, settings.anchor)
    entry(placement, "對齊位移 x", "offset_x", value=settings.offset_x)
    entry(placement, "對齊位移 y", "offset_y", value=settings.offset_y)
    ttk.Label(placement, text="below-minimap 用小地圖的矩形，座標是客戶區座標：").pack(
        anchor="w", pady=(6, 0))
    entry(placement, "小地圖 left", "minimap_left", value=settings.minimap_left)
    entry(placement, "小地圖 top", "minimap_top", value=settings.minimap_top)
    entry(placement, "小地圖 size", "minimap_size", value=settings.minimap_size)
    entry(placement, "小地圖下方間距", "minimap_gap", value=settings.minimap_gap)

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
        form["whitelist"] = [{key: cell.get() for key, cell in record["cells"].items()}
                             for record in whitelist_rows]
        form["waypoints"] = [{"label": label, "x": block.x, "y": block.y}
                             for label, block in settings.waypoints]
        return form

    def do_save() -> None:
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
        for record in list(whitelist_rows):
            record["frame"].destroy()
        whitelist_rows.clear()
        for existing in fresh["whitelist"]:
            add_whitelist_row(existing)
        big_box.delete("1.0", "end")
        big_box.insert("1.0", fresh["big_bosses"])
        status.configure(text=f"已從 {path} 重新載入")

    ttk.Button(actions, text="儲存", command=do_save).pack(side="left")
    ttk.Button(actions, text="重新載入", command=do_reload).pack(side="left", padx=8)
    ttk.Button(actions, text="關閉", command=root.destroy).pack(side="left")
    ttk.Label(actions, text="（overlay 下次啟動時才會讀取這個檔案）",
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


