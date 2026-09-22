"""The profiler client, driven by a fake transport - no network in the tests.

The fixture is a real trimmed response, so the parsing is checked against the shape
the site actually returns, and the fake transport is where the tests stand in for
the network so a failure path can be exercised without one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dfbossreminder.domain.geometry import Block
from dfbossreminder.domain.settings import parse_settings
from dfbossreminder.services.profiler import (
    ProfilerClient,
    ProfilerError,
    account_name,
    fetch_state,
    player_block,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeTransport:
    """A transport that answers from a dictionary of path fragments to bytes."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> bytes:
        self.urls.append(url)
        for fragment, body in self.responses.items():
            if fragment in url:
                return body
        raise AssertionError(f"unexpected url {url}")


def bossmap_bytes() -> bytes:
    return (FIXTURES / "bossmap.json").read_bytes()


def profile_bytes() -> bytes:
    return (FIXTURES / "profile.json").read_bytes()


def client(responses: dict[str, bytes]) -> tuple[ProfilerClient, FakeTransport]:
    transport = FakeTransport(responses)
    return ProfilerClient("https://www.dfprofiler.com", transport=transport, now=lambda: 1234.0), transport


def test_the_bossmap_is_fetched_with_a_cache_busting_parameter() -> None:
    prof, transport = client({"bossmap/json": bossmap_bytes()})
    payload = prof.bossmap()
    assert isinstance(payload, dict) and payload
    assert transport.urls == ["https://www.dfprofiler.com/bossmap/json/?_=1234000"]


def test_the_profile_is_fetched_for_the_configured_user() -> None:
    prof, transport = client({"profile/json/14008279": profile_bytes()})
    payload = prof.profile("14008279")
    assert account_name(payload) == "tommy660"
    assert transport.urls == ["https://www.dfprofiler.com/profile/json/14008279?_=1234000"]


def test_a_profile_without_a_user_id_is_refused_before_any_request() -> None:
    prof, transport = client({})
    with pytest.raises(ProfilerError):
        prof.profile("")
    assert transport.urls == []


def test_the_player_block_comes_from_gpscoords() -> None:
    assert player_block(json.loads(profile_bytes())) == Block(1057, 1017)


def test_a_profile_without_gpscoords_means_unknown_not_the_origin() -> None:
    assert player_block({"username": "x"}) is None
    assert player_block({"gpscoords": []}) is None
    assert player_block({"gpscoords": ["1057"]}) is None
    assert player_block({"gpscoords": ["a", "b"]}) is None
    assert player_block(None) is None
    assert player_block("nonsense") is None


def test_gpscoords_are_accepted_even_though_they_are_published_as_strings() -> None:
    assert player_block({"gpscoords": ["1057", "1017"]}) == Block(1057, 1017)
    assert player_block({"gpscoords": [1057, 1017]}) == Block(1057, 1017)


def test_a_transport_failure_is_a_profiler_error_with_a_useful_message() -> None:
    def broken(url: str, timeout: float) -> bytes:
        raise OSError("connection reset")

    prof = ProfilerClient("https://www.dfprofiler.com", transport=broken)
    with pytest.raises(ProfilerError) as error:
        prof.bossmap()
    assert "connection reset" in str(error.value)


def test_a_non_json_body_is_reported_as_such() -> None:
    prof, _ = client({"bossmap/json": b"<html>not found</html>"})
    with pytest.raises(ProfilerError) as error:
        prof.bossmap()
    assert "not JSON" in str(error.value)


def test_an_empty_body_is_reported() -> None:
    prof, _ = client({"bossmap/json": b""})
    with pytest.raises(ProfilerError):
        prof.bossmap()


def test_a_json_body_that_is_not_an_object_is_reported() -> None:
    prof, _ = client({"bossmap/json": b"[1, 2, 3]"})
    with pytest.raises(ProfilerError):
        prof.bossmap()


def test_fetch_state_groups_the_two_requests_and_parses_both() -> None:
    prof, transport = client({"bossmap/json": bossmap_bytes(), "profile/json/14008279": profile_bytes()})
    settings = parse_settings({"user_id": "14008279", "radius_blocks": 10})
    events, player, name = fetch_state(prof, settings)
    assert events and all(not event.is_mission for event in events)
    assert player == Block(1057, 1017)
    assert name == "tommy660"
    assert len(transport.urls) == 2


def test_fetch_state_skips_the_profile_when_no_user_id_is_set() -> None:
    prof, transport = client({"bossmap/json": bossmap_bytes()})
    events, player, name = fetch_state(prof, parse_settings({}))
    assert events and player is None and name == ""
    assert len(transport.urls) == 1
