"""The dfprofiler HTTP API, read-only, over the standard library.

Two endpoints, both public and both already used by the game's own community
tools:

* ``/bossmap/json/?_=<ms>``  - every live event, each with its spawn blocks;
* ``/profile/json/<user_id>?_=<ms>`` - one account, whose ``gpscoords`` field is
  the account's last known map block.

The transport is injected rather than called directly. That is not indirection for
its own sake: it is what lets the parsing and the settings be tested with the
recorded payloads in ``tests/fixtures`` instead of a live network, and it is what
let this project be developed on a Mac with no game running at all.

Nothing here writes. A ``GET`` is the only request the tool ever makes.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from ..domain.geometry import Block
from ..domain.settings import Settings

# The boss map answers a plain GET, but only with the headers its own page sends;
# without the Referer and the XHR marker it returns the HTML page instead of JSON.
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.5",
    "X-Requested-With": "XMLHttpRequest",
}


class ProfilerError(RuntimeError):
    """A fetch failed. The message is what the panel shows on its status line."""


def _default_transport(url: str, timeout: float) -> bytes:
    referer = f"{url.split('/json/')[0]}"
    headers = dict(BASE_HEADERS)
    headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https host
        return response.read()


class ProfilerClient:
    """Reads the boss map and profiles from dfprofiler."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 25.0,
        transport=None,  # noqa: ANN001 - callable(url, timeout) -> bytes
        now=None,  # noqa: ANN001 - callable() -> float, injected for a deterministic cache key
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._transport = transport or _default_transport
        self._now = now or time.time

    # ------------------------------------------------------------------ fetching
    def _get_json(self, path: str) -> object:
        url = f"{self.base_url}{path}"
        try:
            raw = self._transport(url, self.timeout)
        except urllib.error.HTTPError as error:
            raise ProfilerError(f"HTTP {error.code} from {url}") from error
        except urllib.error.URLError as error:
            raise ProfilerError(f"cannot reach {url}: {error.reason}") from error
        except TimeoutError as error:
            raise ProfilerError(f"timeout fetching {url}") from error
        except OSError as error:
            raise ProfilerError(f"network error fetching {url}: {error}") from error
        if not raw:
            raise ProfilerError(f"empty response from {url}")
        try:
            return json.loads(raw.decode("utf-8", "replace"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProfilerError(f"the response from {url} was not JSON: {error}") from error

    def bossmap(self) -> dict:
        """The boss-map payload. One cache-busting query parameter, as the site expects."""
        payload = self._get_json(f"/bossmap/json/?_={int(self._now() * 1000)}")
        if not isinstance(payload, dict):
            raise ProfilerError("the boss map did not return an object")
        return payload

    def profile(self, user_id: str) -> dict:
        """One account's payload, whose ``gpscoords`` is the player's block."""
        if not user_id:
            raise ProfilerError("no user id is configured")
        payload = self._get_json(f"/profile/json/{user_id}?_={int(self._now() * 1000)}")
        if not isinstance(payload, dict):
            raise ProfilerError(f"the profile for {user_id} did not return an object")
        return payload


def player_block(profile_payload: object, user_id: str = "") -> Block | None:
    """The player's map block, read from a profile payload's ``gpscoords``.

    Read as a decision, not a fetch, so it can be tested against a payload. The
    profiler publishes ``gpscoords`` only when the account has a known position
    (the game reports it while the character is online), so an absent or
    malformed field means "position unknown" and never a guessed ``(0, 0)`` -
    which would silently claim the player is at the origin of the map.
    """
    if not isinstance(profile_payload, dict):
        return None
    coords = profile_payload.get("gpscoords")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        return None
    try:
        x, y = int(str(coords[0]).strip()), int(str(coords[1]).strip())
    except (TypeError, ValueError):
        return None
    return Block(x, y)


def account_name(profile_payload: object) -> str:
    """The display name, for the panel header; empty when it is not published."""
    if not isinstance(profile_payload, dict):
        return ""
    override = profile_payload.get("override")
    if isinstance(override, dict) and isinstance(override.get("account_name"), str):
        return override["account_name"]
    name = profile_payload.get("username_header") or profile_payload.get("username")
    return name if isinstance(name, str) else ""


def fetch_state(client: ProfilerClient, settings: Settings) -> tuple[list, Block | None, str]:
    """One refresh: the boss events, the player's block, and the account name.

    Grouped here so the loop in ``app`` has one call to make and one thing to get
    wrong, and so a test can drive the whole refresh with a fake client.
    """
    from ..domain.bosses import parse_bossmap

    now = time.time()
    payload = client.bossmap()
    events = parse_bossmap(payload, now, include_missions=settings.include_missions)
    player = None
    name = ""
    if settings.user_id:
        profile = client.profile(settings.user_id)
        player = player_block(profile, settings.user_id)
        name = account_name(profile)
    return events, player, name
