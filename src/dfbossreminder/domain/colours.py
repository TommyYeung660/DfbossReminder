"""Colours, parsed once and in one place.

Both the settings (the six themed colours) and the coordinate styles (a colour per rule)
need to turn what a person typed into three channel values, and a style rule also needs
to accept a *name* - the player asked for "red", not for a hex code. Keeping that here
rather than in either of them is also what stops ``settings`` and ``styles`` from
importing each other.
"""

from __future__ import annotations

# A few names, because "show it in red" is how the request was made, and reciting a hex
# code from memory is not a reasonable thing to ask of someone arranging colours.
COLOUR_WORDS = {
    "red": "#FF3333",
    "orange": "#FF9900",
    "yellow": "#FFE000",
    "green": "#33FF33",
    "cyan": "#33FFFF",
    "blue": "#5599FF",
    "purple": "#CC66FF",
    "pink": "#FF66CC",
    "white": "#FFFFFF",
}


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """``"#33FF33"`` -> ``(51, 255, 51)``; anything unparseable becomes white."""
    text = (value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(char * 2 for char in text)
    if len(text) != 6:
        return (255, 255, 255)
    try:
        number = int(text, 16)
    except ValueError:
        return (255, 255, 255)
    return ((number >> 16) & 0xFF, (number >> 8) & 0xFF, number & 0xFF)


def normalize_colour(value: str) -> str | None:
    """A hex code or a colour name as ``#RRGGBB``, or None when it is neither.

    Returning None rather than a default is the point: a mistyped colour in a settings
    file should be reported, not silently drawn in white.
    """
    text = (value or "").strip()
    word = COLOUR_WORDS.get(text.lower())
    if word:
        return word
    candidate = text if text.startswith("#") else f"#{text}"
    if len(candidate) != 7:
        return None
    try:
        int(candidate[1:], 16)
    except ValueError:
        return None
    return candidate.upper()
