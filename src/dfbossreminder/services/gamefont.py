"""The client's own font, extracted from the copy the player already has.

The readout is meant to look like the game's HUD, and the game's HUD font is not
installed on the machine - it is a freeware face called **VIPER NORA** (Dimitris K.,
pOPdOG fONTS, 1999) baked into the client's Unity assets, which is exactly why the
game looks the way it does. Naming it as a font family would find nothing.

So the font is taken from the client's own files:

* the asset is only **read** - the same read-only posture as everything else here;
* the extracted face is written to this project's own cache directory and loaded
  **privately** into this process (``FR_PRIVATE``), so nothing is installed system-wide
  and the player's font list is untouched;
* nothing is redistributed: the bytes come from the installation of the game the tool
  is already reading, and they are never committed to this repository.

The family name is read out of the TTF's own ``name`` table rather than assumed, and
the extraction is validated by the table directory: a candidate is accepted only when
its ``name`` table actually contains the family being looked for. That check is what
makes the scan safe on a 200 MB asset full of coincidental ``\\x00\\x01\\x00\\x00``
sequences.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

SFNT_VERSION = b"\x00\x01\x00\x00"
FONT_FAMILY = "VIPER NORA"
# The tables a real TrueType outline font must have; used to reject a coincidental
# header match before the more expensive name-table check.
REQUIRED_TABLES = (b"name", b"glyf", b"head", b"loca")
CACHE_NAME = "game-font.ttf"

# How far back from the family name to look for the font header. The header sits a few
# kilobytes before its own name table in practice; the window is generous but bounded,
# so a missing font costs a scan of megabytes rather than a scan of the whole asset.
DEFAULT_WINDOW = 4 * 1024 * 1024

MAX_NAME_LENGTH = 128
MAX_TABLES = 60


class FontNotFound(LookupError):
    """The family was not found in the bytes that were searched."""


@dataclass(frozen=True)
class EmbeddedFont:
    offset: int
    length: int
    family: str


def table_directory(blob: bytes, offset: int) -> dict[bytes, tuple[int, int]] | None:
    """An sfnt table directory at ``offset``, or ``None`` if there is not one there."""
    if offset < 0 or offset + 12 > len(blob) or blob[offset:offset + 4] != SFNT_VERSION:
        return None
    count = struct.unpack_from(">H", blob, offset + 4)[0]
    if not 4 <= count <= MAX_TABLES or offset + 12 + count * 16 > len(blob):
        return None
    tables: dict[bytes, tuple[int, int]] = {}
    for index in range(count):
        entry = blob[offset + 12 + index * 16: offset + 12 + index * 16 + 16]
        tag = entry[0:4]
        table_offset, length = struct.unpack_from(">II", entry, 8)
        if table_offset + length > len(blob) - offset:
            return None              # a table that runs past the data is not a font
        tables[tag] = (table_offset, length)
    return tables


def family_names(blob: bytes, offset: int, tables: dict[bytes, tuple[int, int]]) -> list[str]:
    """Every family/subfamily string in the font's ``name`` table.

    Both the Windows (UTF-16BE) and Mac (single-byte) records are read, because the
    1999 freeware fonts use the Mac encoding for some records - which is how the same
    name turns up decoded as ``'\\x00V\\x00I\\x00P…'`` alongside the readable copy.
    """
    table_offset, table_length = tables[b"name"]
    table = blob[offset + table_offset: offset + table_offset + table_length]
    if len(table) < 6:
        return []
    count, strings = struct.unpack_from(">HH", table, 2)
    names: list[str] = []
    for index in range(min(count, MAX_TABLES * 2)):
        entry = table[6 + index * 12: 6 + index * 12 + 12]
        if len(entry) < 12:
            break
        platform, _encoding, _language, name_id, length, string_offset = struct.unpack(">6H", entry)
        if name_id not in (1, 4) or length == 0 or length > MAX_NAME_LENGTH:
            continue
        raw = table[strings + string_offset: strings + string_offset + length]
        if len(raw) < length:
            continue
        try:
            text = raw.decode("utf-16-be") if platform == 3 else raw.decode("latin-1")
        except UnicodeDecodeError:
            continue
        names.append(text.replace("\x00", "").strip())
    return names


def font_extent(tables: dict[bytes, tuple[int, int]]) -> int:
    """How long the font is, from its tables, padded to a four-byte boundary."""
    end = 0
    for table_offset, length in tables.values():
        end = max(end, table_offset + length)
    return (end + 3) & ~3


def find_embedded_font(
    blob: bytes,
    family: str = FONT_FAMILY,
    window: int = DEFAULT_WINDOW,
    search_from: int = 0,
    search_to: int | None = None,
) -> EmbeddedFont | None:
    """The family's TrueType bytes inside ``blob``, or ``None``.

    The name is located first and the header then searched for *backwards* from it,
    which is what keeps this affordable: a forward scan would have to validate the
    whole asset, while this only validates the candidates between the name and the
    header that produced it. A candidate counts only when its own ``name`` table
    covers that exact string, so a coincidental header in the data cannot win.
    """
    for needle in (family.encode("utf-16-be"), family.encode("ascii")):
        at = blob.find(needle, search_from, search_to)
        if at == -1:
            continue
        floor = max(search_from, at - window)
        for candidate in range(at, floor - 1, -1):
            if blob[candidate:candidate + 4] != SFNT_VERSION:
                continue
            tables = table_directory(blob, candidate)
            if not tables or any(tag not in tables for tag in REQUIRED_TABLES):
                continue
            table_offset, table_length = tables[b"name"]
            if not (candidate + table_offset <= at < candidate + table_offset + table_length):
                continue
            names = family_names(blob, candidate, tables)
            if not any(name.strip().upper() == family.strip().upper() for name in names):
                continue
            return EmbeddedFont(offset=candidate, length=font_extent(tables), family=family)
    return None


def extract(blob: bytes, family: str = FONT_FAMILY) -> bytes:
    """The font's bytes, or :class:`FontNotFound`."""
    found = find_embedded_font(blob, family)
    if found is None:
        raise FontNotFound(f"{family} was not found in these bytes")
    return blob[found.offset: found.offset + found.length]


def font_asset_candidates(data_dir: Path) -> list[Path]:
    """The asset files worth searching, biggest first.

    The font lives in a ``sharedassets`` file rather than in ``resources.assets`` on
    this client, and which one holds it is not documented, so they are all searched -
    the small ones first would be quicker but the family is in the largest here, and
    ordering by size means the common case hits on the first file.
    """
    files = [path for path in data_dir.glob("sharedassets*.assets")]
    files.append(data_dir / "resources.assets")
    return sorted((path for path in files if path.exists()),
                  key=lambda path: path.stat().st_size, reverse=True)


def ensure_cached(cache: Path, data_dir: Path, family: str = FONT_FAMILY) -> Path | None:
    """Extract the font into ``cache`` once, and return it thereafter.

    Cached on purpose: the search reads a 200 MB asset, and the answer never changes
    for a given installation. The file lives in this project's own state directory,
    never in the repository.
    """
    if cache.exists() and cache.stat().st_size > 0:
        return cache
    for asset in font_asset_candidates(data_dir):
        try:
            blob = asset.read_bytes()
        except OSError:
            continue
        found = find_embedded_font(blob, family)
        if found is None:
            continue
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(blob[found.offset: found.offset + found.length])
        except OSError:
            return None
        return cache
    return None
