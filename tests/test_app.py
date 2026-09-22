"""The process: settings that stick, overrides, one-shot output, and the loop.

The loop is driven by a fake client and a fake presenter, so a fetch, a plan, a
draw, a failure and a stale plan are all exercised without a network or a window.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dfbossreminder import app
from dfbossreminder.domain.settings import Settings, parse_settings
from dfbossreminder.services.window import Rect
from dfbossreminder.ui.panel import Row

PROFILE = {"gpscoords": ["1057", "1017"], "override": {"account_name": "tommy660"}}
BOSS = {
    "1": {"game_id": "1", "locations": [["1057", "1018"]], "special_enemy_type": "Bandits",
          "special_enemy_amount": "2", "boss_num": "1", "event_type": "",
          "start_time": "1", "end_time": "9999999999"},
    "2": {"game_id": "2", "locations": [["1200", "1200"]], "special_enemy_type": "Titan",
          "special_enemy_amount": "1", "boss_num": "2", "event_type": "",
          "start_time": "1", "end_time": "9999999999"},
}


class FakeClient:
    def __init__(self, bossmap=None, profile=None, fail: str = "") -> None:
        self.bossmap_payload = bossmap if bossmap is not None else BOSS
        self.profile_payload = profile if profile is not None else PROFILE
        self.fail = fail
        self.bossmap_calls = 0
        self.profile_calls = 0

    def bossmap(self) -> dict:
        self.bossmap_calls += 1
        if self.fail == "bossmap":
            raise app.ProfilerError("boom")
        return self.bossmap_payload

    def profile(self, user_id: str) -> dict:
        self.profile_calls += 1
        if self.fail == "profile":
            raise app.ProfilerError("no profile")
        return self.profile_payload


class FakePresenter:
    kind = "console"

    def __init__(self, hot: str | None = None) -> None:
        self.draws: list = []
        self.hot = hot
        self.closed = False

    def draw(self, plan, settings, account, status, stale):  # noqa: ANN001
        self.draws.append({"plan": plan, "account": account, "status": status, "stale": stale})

    def follow(self, window):  # noqa: ANN001
        return ""

    def hotkey(self):  # noqa: ANN001
        return self.hot

    def describe(self) -> str:
        return "fake"

    def close(self) -> None:
        self.closed = True


# --------------------------------------------------------------------- settings


def test_settings_are_remembered_in_a_file_the_tool_reads_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    app.save_settings(path, parse_settings({"user_id": "14008279", "radius_blocks": 20,
                                            "whitelist_mode": True, "whitelist": "1055,986:1"}))
    again = app.load_settings(path)
    assert again.user_id == "14008279"
    assert again.radius_blocks == 20
    assert again.whitelist_mode
    assert str(again.whitelist[0].block) == "1055,986"


def test_a_missing_settings_file_means_defaults() -> None:
    assert app.load_settings(Path("/nonexistent/settings.json")) == Settings()


def test_a_corrupt_settings_file_does_not_stop_the_tool(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    assert app.load_settings(path) == Settings()


def test_a_user_id_on_the_command_line_is_validated_and_saved() -> None:
    args = app.build_parser().parse_args(["--user-id", "14008279"])
    settings, save = app.apply_overrides(Settings(), args)
    assert settings.user_id == "14008279"
    assert save


def test_a_name_instead_of_an_id_is_refused_with_the_expected_shape() -> None:
    args = app.build_parser().parse_args(["--user-id", "tommy660"])
    with pytest.raises(SystemExit) as error:
        app.apply_overrides(Settings(), args)
    assert "14008279" in str(error.value)


def test_the_radius_and_whitelist_are_settable_and_remembered() -> None:
    args = app.build_parser().parse_args(
        ["--radius", "25", "--whitelist", "1055,986;1057,1017:2", "--whitelist-mode", "on"])
    settings, save = app.apply_overrides(Settings(), args)
    assert settings.radius_blocks == 25
    assert len(settings.whitelist) == 2
    assert settings.whitelist_mode
    assert save


def test_whitelist_add_appends_rather_than_replacing() -> None:
    start = parse_settings({"whitelist": "1055,986"})
    args = app.build_parser().parse_args(["--whitelist-add", "1057,1017"])
    settings, _ = app.apply_overrides(start, args)
    assert {str(entry.block) for entry in settings.whitelist} == {"1055,986", "1057,1017"}


def test_a_bad_whitelist_on_the_command_line_names_itself() -> None:
    args = app.build_parser().parse_args(["--whitelist", "nonsense"])
    with pytest.raises(SystemExit) as error:
        app.apply_overrides(Settings(), args)
    assert "nonsense" in str(error.value)


def test_no_save_keeps_a_one_off_run_out_of_the_file() -> None:
    args = app.build_parser().parse_args(["--radius", "12", "--no-save"])
    settings, save = app.apply_overrides(Settings(), args)
    assert settings.radius_blocks == 12
    assert not save


# --------------------------------------------------------------------- one shot


def test_run_once_prints_the_plan_and_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "plan.json"
    lines: list[str] = []
    code = app.run_once(parse_settings({"user_id": "14008279", "radius_blocks": 5}),
                        FakeClient(), str(out), log=lines.append)
    assert code == 0
    assert any("Bandits" in line for line in lines)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["player"] == {"x": 1057, "y": 1017}
    assert payload["counts"]["shown"] == 1          # only the bandit is within 5 blocks
    assert payload["rows"][0]["distance"] == 1
    assert payload["rows"][0]["bearing"] == "1下"
    # The export carries both the note's code and its text, so a machine and a person
    # can each read what the run thought it was doing.
    assert payload["notes"][0]["code"] == "within"
    assert payload["notes"][0]["text"] == "5 格內"


def test_run_once_reports_a_fetch_failure_rather_than_raising() -> None:
    lines: list[str] = []
    code = app.run_once(parse_settings({"user_id": "14008279"}), FakeClient(fail="bossmap"),
                        log=lines.append)
    assert code == 1
    assert any("boom" in line for line in lines)


def test_main_with_no_user_id_tells_the_player_what_to_do(capsys) -> None:  # noqa: ANN001
    code = app.main(["--settings", "/nonexistent/dir/settings.json", "--show-config"])
    assert code == 0        # --show-config is allowed without an id


# --------------------------------------------------------------------- the loop


def watch(settings=None, client=None, presenter=None, path=None) -> tuple[app.Watch, FakePresenter]:  # noqa: ANN001
    presenter = presenter or FakePresenter()
    settings = settings or parse_settings({"user_id": "14008279", "radius_blocks": 5,
                                           "poll_seconds": 20})
    watch = app.Watch(settings, client or FakeClient(), presenter,
                      path or Path("/nonexistent/settings.json"), log=lambda *_a: None)
    return watch, presenter


def test_the_first_tick_fetches_and_draws_the_nearby_boss() -> None:
    watch_obj, presenter = watch()
    watch_obj.tick(1000.0)
    assert watch_obj.events
    assert len(presenter.draws) == 1
    plan = presenter.draws[0]["plan"]
    assert [row.name for row in plan.rows] == ["Bandits"]
    assert presenter.draws[0]["stale"] is False
    assert "已更新" in presenter.draws[0]["status"]


def test_a_fetch_failure_keeps_the_last_plan_and_marks_it_stale() -> None:
    client = FakeClient()
    watch_obj, presenter = watch(client=client)
    watch_obj.tick(1000.0)                    # good fetch
    client.fail = "bossmap"
    watch_obj.tick(1000.0 + watch_obj.settings.stale_seconds + 1)
    # The old plan is still drawn, and it says it is old rather than pretending.
    assert presenter.draws[-1]["stale"] is True
    assert "過期" in presenter.draws[-1]["status"]
    assert presenter.draws[-1]["plan"].rows


def test_a_failure_before_any_success_says_so_and_draws_nothing() -> None:
    watch_obj, presenter = watch(client=FakeClient(fail="bossmap"))
    watch_obj.tick(1000.0)
    assert presenter.draws[-1]["stale"] is True
    assert "尚未取得資料" in presenter.draws[-1]["status"]
    assert presenter.draws[-1]["plan"].rows == ()


def test_the_fetch_is_gated_by_the_poll_interval() -> None:
    client = FakeClient()
    watch_obj, _ = watch(client=client)
    watch_obj.tick(1000.0)
    watch_obj.tick(1001.0)                    # too soon: no second fetch
    assert client.bossmap_calls == 1
    watch_obj.tick(1000.0 + watch_obj.settings.poll_seconds + 0.1)
    assert client.bossmap_calls == 2


def test_the_toggle_hotkey_flips_the_mode_and_saves_it(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    presenter = FakePresenter(hot="toggle-whitelist")
    settings = parse_settings({"user_id": "14008279", "whitelist": "1057,1018"})
    watch_obj, _ = watch(settings=settings, presenter=presenter, path=path)
    assert not watch_obj.settings.whitelist_mode
    watch_obj.tick(1000.0)                    # hotkey fires before the draw
    assert watch_obj.settings.whitelist_mode
    assert app.load_settings(path).whitelist_mode
    # And the plan that was drawn used the new mode: only the watched block.
    assert [row.name for row in presenter.draws[-1]["plan"].rows] == ["Bandits"]


def test_a_position_that_is_unknown_is_never_pretended() -> None:
    watch_obj, presenter = watch(client=FakeClient(profile={"username": "x"}))
    watch_obj.tick(1000.0)
    plan = presenter.draws[-1]["plan"]
    assert plan.player is None
    assert plan.rows[0].distance is None
    assert [note.code for note in plan.notes] == ["no_player"]


def test_the_loop_closes_the_presenter_when_it_stops() -> None:
    watch_obj, presenter = watch()
    watch_obj.run(0.0)
    assert presenter.closed


# --------------------------------------------------------------------- the entry


def test_the_overlay_falls_back_to_the_console_off_windows() -> None:
    # The tool must be runnable on a development machine, and the fallback must be
    # announced rather than silently changing what the player sees.
    notes: list[str] = []
    presenter = app.make_presenter(parse_settings({"presentation": "overlay"}), log=notes.append)
    assert presenter.kind == "console"
    assert any("falling back" in note for note in notes)


def test_the_console_presentation_is_always_available() -> None:
    assert app.make_presenter(parse_settings({"presentation": "console"})).kind == "console"


def test_the_cli_prints_the_effective_settings() -> None:
    code = app.main(["--settings", "/nonexistent/settings.json", "--show-config",
                     "--radius", "15", "--no-save"])
    assert code == 0


def test_a_missing_standard_stream_does_not_crash_the_entry_point(monkeypatch) -> None:  # noqa: ANN001
    # A --noconsole build has no stdout; printing to None would raise on the first
    # message, before the overlay ever appeared.
    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    assert app.main(["--settings", "/nonexistent/settings.json", "--show-config"]) == 0


# ------------------------------------------------------- requirement: no game, no overlay


def test_the_overlay_is_refused_when_the_game_is_not_running(monkeypatch) -> None:  # noqa: ANN001
    # The overlay is a readout of the running client: no client, no rectangle to
    # anchor to and no player to measure from. It must not be opened somewhere
    # arbitrary, and it must not silently become a console either.
    monkeypatch.setattr(app, "find_game_window", lambda *a, **k: None)
    with pytest.raises(app.GameNotRunning) as error:
        app.game_window_or_refuse(log=lambda *_: None)
    assert "not running" in str(error.value)


def test_make_presenter_lets_the_refusal_out_rather_than_falling_back(monkeypatch) -> None:  # noqa: ANN001
    # make_presenter degrades to the console for a missing OS feature, but a missing
    # game is a different answer, so the refusal must not be swallowed.
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app, "find_game_window", lambda *a, **k: None)
    with pytest.raises(app.GameNotRunning):
        app.make_presenter(parse_settings({"presentation": "overlay"}), log=lambda *_: None)
    with pytest.raises(app.GameNotRunning):
        app.make_presenter(parse_settings({"presentation": "panel"}), log=lambda *_: None)


def test_the_console_presentation_still_runs_without_the_game() -> None:
    # Checking the tool before starting the game is the whole point of the console
    # mode, so it is never gated on the client.
    assert app.make_presenter(parse_settings({"presentation": "console"})).kind == "console"


def test_main_reports_the_refusal_and_exits_non_zero(monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setattr(app, "find_game_window", lambda *a, **k: None)
    code = app.main(["--settings", "/nonexistent/settings.json", "--user-id", "14008279",
                     "--presentation", "overlay", "--no-save"])
    assert code == 3
    assert "not running" in capsys.readouterr().err


def test_the_config_window_is_a_documented_option() -> None:
    args = app.build_parser().parse_args(["--config"])
    assert args.config is True


# --------------------------------------------------------------------- the settings window


def test_the_settings_window_round_trips_every_field() -> None:
    # The window is only useful if "load, show, save" is the same settings. This drives
    # the pure half of it, so the rule is checked without a display.
    from dfbossreminder.ui.config_gui import describe_round_trip

    original = parse_settings({
        "user_id": "14008279", "radius_blocks": 15, "whitelist_mode": True,
        "whitelist": "1055,986:2=Bunker;1057,1017", "font_size": 14,
        "colours": {"list": "#00FF00", "big": "#FFFF00"}, "opacity": 0.7,
        "anchor": "below-minimap", "minimap_gap": 6, "big_bosses": ["Devil Hound"],
        "width": 340, "height": 200, "max_rows": 14,
    })
    report = describe_round_trip(original)
    assert report["stable"], report["notes"]
    assert report["notes"] == []


def test_the_settings_window_reports_a_value_it_had_to_change() -> None:
    # A radius of 9999 is stored as 200; the window must say so rather than let the
    # player believe the file holds what they typed.
    from dfbossreminder.ui.config_gui import normalized, payload_from_form

    payload = payload_from_form({"radius_blocks": "9999", "font_size": "not a number"})
    settings, notes = normalized(payload)
    assert settings.radius_blocks == 200
    assert any(note.startswith("radius_blocks") for note in notes)


def test_a_half_typed_whitelist_row_is_dropped_rather_than_saved_as_a_coordinate() -> None:
    from dfbossreminder.ui.config_gui import payload_from_form

    payload = payload_from_form({"whitelist": [{"x": "1055", "y": "986", "radius": "1"},
                                               {"x": "", "y": "1000", "radius": "0"}]})
    assert len(payload["whitelist"]) == 1
    assert payload["whitelist"][0]["radius"] == 1


# ------------------------------------------------- the readout sizes itself


class StubOverlay:
    """Just enough overlay for the sizing rule, which is where a clip would hide."""

    def __init__(self, rows_fitting: int, line_height: int = 15, title_height: int = 18) -> None:
        self.rows_fitting = rows_fitting
        self.line_height = line_height
        self.title_height = title_height
        self.height = title_height + rows_fitting * line_height + 5
        self.top = 100
        self.left = 200

    def height_for(self, rows: int) -> int:
        return self.title_height + rows * self.line_height + 5

    def resize(self, left: int, top: int, width: int, height: int) -> None:
        self.left, self.top, self.height = left, top, height

    def set_content(self, title: str, rows: tuple) -> None:  # noqa: ANN001
        self.title, self.rows = title, rows


def presenter_with(fitting: int) -> app.OverlayPresenter:
    """A presenter whose overlay is a stub, so no Windows call is made."""
    presenter = app.OverlayPresenter.__new__(app.OverlayPresenter)
    presenter.settings = parse_settings({})
    presenter.use_client_area = True
    # A client rectangle to measure against, so the sizing rule is exercised without a
    # game: the presenter's own arithmetic is what is under test.
    presenter.window = type("W", (), {"client": Rect(0, 0, 1280, 720),
                                      "exclusive_fullscreen": False})()
    presenter.notes = []
    presenter.hotkey_registered = False
    presenter.overlay = StubOverlay(fitting)
    return presenter


def test_the_window_grows_to_fit_its_rows() -> None:
    # A fixed height dropped the tail of the list, and the tail is the notes.
    presenter = presenter_with(20)
    rows = tuple(Row(f"row {index}") for index in range(12))
    kept = presenter._fit(rows, parse_settings({}))
    assert kept == rows
    assert presenter.overlay.height >= presenter.overlay.height_for(12) - 1


def test_rows_over_the_maximum_height_are_reported_not_dropped_silently() -> None:
    presenter = presenter_with(6)
    rows = tuple(Row(f"row {index}") for index in range(20))
    kept = presenter._fit(rows, parse_settings({"height": presenter.overlay.height}))
    assert len(kept) == 6
    assert kept[-1].text == "（還有 15 行未顯示）"       # 20 - 6 + 1
    assert kept[-1].colour == parse_settings({}).colour("note")


def test_the_last_row_is_never_the_one_that_disappears() -> None:
    # The notes are the last rows, and they are what says whether an empty readout is
    # correct; a trim that lost them would hide the explanation.
    presenter = presenter_with(4)
    rows = (Row("boss"), Row("boss"), Row("waypoint"), Row("10 格內"), Row("已更新 0 秒前"))
    kept = presenter._fit(rows, parse_settings({"height": presenter.overlay.height}))
    assert "未顯示" in kept[-1].text


def test_the_hotkey_is_configurable_because_f8_is_not_always_free() -> None:
    # On the game PC something else already holds F8, and a toggle that cannot register
    # is a toggle that does not exist.
    assert parse_settings({}).hotkey == "F8"
    assert parse_settings({"hotkey": "f6"}).hotkey == "F6"
    args = app.build_parser().parse_args(["--hotkey", "F6"])
    settings, save = app.apply_overrides(Settings(), args)
    assert settings.hotkey == "F6" and save


# --------------------------------------------- the console's encoding


def test_the_streams_are_pinned_to_utf8() -> None:
    # Not left to the environment: the frozen exe ignores PYTHONIOENCODING, so a
    # redirected log came back as Big5 bytes. UTF-8 is also right for a console, since
    # Windows writes to a console through WriteConsoleW (PEP 528) and only decodes our
    # bytes on the way through.
    class Stream:
        def __init__(self) -> None:
            self.options: dict = {}

        def reconfigure(self, **options) -> None:  # noqa: ANN003
            self.options = options

    out, err = Stream(), Stream()
    original = (app.sys.stdout, app.sys.stderr)
    try:
        app.sys.stdout, app.sys.stderr = out, err
        app._make_streams_safe()
    finally:
        app.sys.stdout, app.sys.stderr = original
    for stream in (out, err):
        assert stream.options["encoding"] == "utf-8"
        assert stream.options["errors"] == "replace"
        assert stream.options["line_buffering"]
