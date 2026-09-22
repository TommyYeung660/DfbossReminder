"""The window measurement logic, driven by a fake ``user32``.

``measure_window`` needs no Windows of its own: it asks the API for a client
rectangle, a screen origin and a title, so a small fake stands in for the OS and the
arithmetic that turns those into a placement - and the fullscreen heuristic - is
checked here rather than on the game PC.
"""

from __future__ import annotations

from dfbossreminder.services.window import Rect, measure_window


class FakeUser32:
    """The handful of calls the measurement makes, with scripted answers."""

    def __init__(self, client=(0, 0, 1280, 720), origin=(100, 50), title="Dead Frontier",
                 pid=4242, failed: set[str] | None = None) -> None:
        self.client = client
        self.origin = origin
        self.title = title
        self.pid = pid
        self.failed = failed or set()
        self.calls: list[str] = []

    def GetClientRect(self, hwnd, rect):  # noqa: ANN001, N802
        self.calls.append("GetClientRect")
        if "GetClientRect" in self.failed:
            return 0
        left, top, right, bottom = self.client
        target = rect._obj          # ctypes.byref hands the fake a CArgObject
        target.left, target.top = left, top
        target.right, target.bottom = right, bottom
        return 1

    def ClientToScreen(self, hwnd, point):  # noqa: ANN001, N802
        self.calls.append("ClientToScreen")
        if "ClientToScreen" in self.failed:
            return 0
        target = point._obj
        target.x += self.origin[0]
        target.y += self.origin[1]
        return 1

    def GetWindowThreadProcessId(self, hwnd, pid):  # noqa: ANN001, N802
        self.calls.append("GetWindowThreadProcessId")
        pid._obj.value = self.pid
        return 1

    def GetWindowTextW(self, hwnd, buffer, size):  # noqa: ANN001, N802
        self.calls.append("GetWindowTextW")
        buffer.value = self.title
        return len(self.title)


SCREEN_1080P = Rect(0, 0, 1920, 1080)


def test_the_client_rectangle_is_reported_in_screen_coordinates() -> None:
    window = measure_window(FakeUser32(), 7, screen=SCREEN_1080P)
    assert window is not None
    assert window.client == Rect(100, 50, 1280, 720)
    assert window.pid == 4242
    assert window.title == "Dead Frontier"


def test_the_client_origin_is_added_to_the_window_origin() -> None:
    # GetClientRect is relative to the window, so a window docked at (300, 200) must
    # place its client area there - not at the client's own (0, 0).
    window = measure_window(FakeUser32(origin=(300, 200)), 7, screen=SCREEN_1080P)
    assert window is not None
    assert (window.client.left, window.client.top) == (300, 200)


def test_a_windowed_client_is_not_reported_as_fullscreen() -> None:
    window = measure_window(FakeUser32(client=(0, 0, 1280, 720)), 7, screen=SCREEN_1080P)
    assert window is not None
    assert not window.exclusive_fullscreen
    assert "1280x720" in window.presentation_note


def test_a_client_covering_the_monitor_is_reported_as_a_fullscreen_risk() -> None:
    window = measure_window(FakeUser32(client=(0, 0, 1920, 1080)), 7, screen=SCREEN_1080P)
    assert window is not None
    assert window.exclusive_fullscreen
    assert "fullscreen" in window.presentation_note


def test_a_failed_measurement_returns_none_rather_than_a_partial_window() -> None:
    assert measure_window(FakeUser32(failed={"GetClientRect"}), 7, screen=SCREEN_1080P) is None
    assert measure_window(FakeUser32(failed={"ClientToScreen"}), 7, screen=SCREEN_1080P) is None


def test_a_degenerate_client_rectangle_is_refused() -> None:
    assert measure_window(FakeUser32(client=(0, 0, 0, 0)), 7, screen=SCREEN_1080P) is None


def test_the_measurement_only_asks_the_os_to_read() -> None:
    fake = FakeUser32()
    measure_window(fake, 7, screen=SCREEN_1080P)
    assert set(fake.calls) == {"GetClientRect", "ClientToScreen",
                               "GetWindowThreadProcessId", "GetWindowTextW"}


def test_a_rect_reports_its_edges_and_containment() -> None:
    rect = Rect(10, 20, 100, 50)
    assert (rect.right, rect.bottom) == (110, 70)
    assert rect.contains(10, 20) and rect.contains(109, 69)
    assert not rect.contains(110, 70)
    assert rect.as_dict() == {"left": 10, "top": 20, "width": 100, "height": 50}
