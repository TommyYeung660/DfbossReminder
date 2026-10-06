"""The bosses the player has ticked away, and when they come back.

The box column on the readout is a dismissal: tick the box on a row and that boss's rows
go, all of them, because a boss is one spawn at several blocks. The third thing the player
asked for is the rule that keeps this from being a filter: **a dismissal must not affect
the next cycle's readout.**

That single rule is what everything here is built around, and it is why this is not a
settings list. A name list in the settings file would be a permanent preference and would
hide the boss for ever; this holds the *cycle keys* of the spawns that were dismissed, and
a spawn that comes back in the next cycle has a different key (see
``BossEvent.cycle_key``) - so it is shown again without anyone having to remember to
un-dismiss it.

The other half is ``keep_only``: a key that the feed no longer reports is a spawn that is
over, so it is dropped. That is what keeps a long session from accumulating keys that can
never match again, and it is the second, independent way a dismissal ends.

Nothing here is persisted, and nothing here is timed. The end of a dismissal is the cycle,
not the clock: a boss that respawns after five minutes is a new cycle, and one that sits
there for an hour is still the one the player ticked away.
"""

from __future__ import annotations

from collections.abc import Collection, KeysView
from dataclasses import dataclass, field

# What identifies one spawn: the game's entry id and the cycle's start time. Spelled out
# here so the type is in one place rather than repeated in every signature.
Key = tuple[str, float]


@dataclass
class Dismissed:
    """The dismissed spawns, as ``key -> the name to say out loud``.

    The labels are kept for one reason: the console says *which* boss was hidden and which
    one came back, and "という key" is of no use to anyone reading a log.
    """

    labels: dict[Key, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.labels)

    def __contains__(self, key: object) -> bool:
        return key in self.labels

    def keys(self) -> KeysView[Key]:
        """The keys, as a container the plan can test membership against."""
        return self.labels.keys()

    def hide(self, key: Key, label: str = "") -> bool:
        """Dismiss a spawn. ``True`` when it was not already dismissed.

        Returning whether anything changed is what lets the caller redraw only on a real
        change: a second click on the same boss (a stale window, a double click that got
        through) must not cost a redraw or a log line.
        """
        if key in self.labels:
            return False
        self.labels[key] = label
        return True

    def keep_only(self, keys: Collection[Key]) -> list[str]:
        """Keep only these keys, and **name what that dropped**, for the log.

        Called after a successful fetch with everything the feed currently reports. A
        dismissal for a spawn that is no longer in the feed has nothing left to hide, so it
        goes - which is how a dismissal ends when the boss is killed, and how the next
        cycle is guaranteed to show its boss even if the key somehow repeated.

        It returns the names rather than a count because a run that says "6 x Bandits is
        back" is a run a person can check, and one that silently forgets is the kind of
        quiet change this project keeps paying for.
        """
        live = set(keys)
        gone = [self.labels[key] or str(key) for key in self.labels if key not in live]
        self.labels = {key: label for key, label in self.labels.items() if key in live}
        return gone
