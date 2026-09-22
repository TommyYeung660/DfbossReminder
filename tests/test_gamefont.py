"""The client's font extractor, against a TrueType file built for the test.

The real font lives inside a 200 MB asset on the game PC, which is exactly the kind of
input a test cannot ship. So the test builds its own minimal TrueType file, embeds it
in a blob of noise that also contains decoy headers, and checks that the extractor
finds the right bytes and refuses every look-alike. That makes the extractor's rule -
"the ``name`` table must contain this family" - checkable on any machine.
"""

from __future__ import annotations

import struct

from dfbossreminder.services.gamefont import (
    FONT_FAMILY,
    EmbeddedFont,
    extract,
    family_names,
    find_embedded_font,
    font_extent,
    table_directory,
)

FAMILY = "TEST FACE"


def build_font(family: str = FAMILY, pad: int = 0) -> bytes:
    """A minimal but structurally valid TrueType file with real table offsets."""
    def name_table() -> bytes:
        # One Windows record (UTF-16BE) and one Mac record, as the 1999 fonts have.
        # The storage offset is measured from the start of the table and must clear the
        # records, which is the field a hand-built table gets wrong.
        windows = family.upper().encode("utf-16-be")
        mac = family.upper().encode("latin-1")
        records = [(3, 1, 0x409, 1, len(windows), 0),
                   (1, 0, 0, 1, len(mac), len(windows))]
        table = struct.pack(">HHH", 0, len(records), 6 + len(records) * 12)
        for record in records:
            table += struct.pack(">6H", *record)
        return table + windows + mac

    tables = {
        b"head": b"\x00" * 54,
        b"loca": b"\x00" * 8,
        b"glyf": b"\x00" * 40,
        b"name": name_table(),
    }
    order = [b"head", b"loca", b"glyf", b"name"]
    header = struct.pack(">IHHHH", 0x00010000, len(order), 0, 0, 0)
    directory = b""
    body = b""
    offset = 12 + len(order) * 16
    for name in order:
        length = len(tables[name])
        directory += name + struct.pack(">III", 0, offset, length)
        # The bodies are padded to four bytes, so the recorded offsets and the real ones
        # agree - a table whose recorded offset runs past the data is rejected by the
        # extractor, which is the check that makes it safe on a 200 MB asset.
        padded = tables[name] + b"\x00" * (((length + 3) & ~3) - length)
        body += padded
        offset += len(padded)
    return b"\x00" * pad + header + directory + body


def test_a_font_built_for_the_test_is_structurally_sound() -> None:
    blob = build_font()
    tables = table_directory(blob, 0)
    assert tables is not None
    assert set(tables) == {b"head", b"loca", b"glyf", b"name"}
    assert FAMILY in family_names(blob, 0, tables)
    assert font_extent(tables) <= len(blob)


def test_the_font_is_found_inside_a_larger_blob() -> None:
    font = build_font()
    blob = b"\xab" * 5000 + font + b"\xcd" * 9000
    found = find_embedded_font(blob, FAMILY)
    assert found == EmbeddedFont(offset=5000, length=len(font), family=FAMILY)
    assert extract(blob, FAMILY) == font


def test_the_extractor_refuses_a_decoy_header_whose_name_table_lacks_the_family() -> None:
    # The asset is full of \\x00\\x01\\x00\\x00 sequences; only a header whose own name
    # table holds the family counts, which is what keeps the scan honest.
    other = build_font("SOMETHING ELSE")
    blob = other + b"\x00" * 64 + build_font()
    found = find_embedded_font(blob, FAMILY)
    assert found is not None
    assert found.offset > len(other)          # the right one, not the decoy
    assert extract(blob, FAMILY) == build_font()


def test_a_font_that_is_not_there_is_reported_not_guessed() -> None:
    blob = b"\x00" * 4000 + b"no fonts here at all" + b"\xff" * 4000
    assert find_embedded_font(blob, FAMILY) is None
    assert find_embedded_font(build_font(), "A DIFFERENT FAMILY") is None


def test_the_search_window_bounds_the_work() -> None:
    # The window bounds how far back from the name the header may be: the alternative is
    # validating every candidate in a 200 MB asset. The test measures the real distance
    # and checks one byte either side of it, rather than assuming a number.
    blob = build_font(pad=200_000)
    found = find_embedded_font(blob, FAMILY, window=1_000_000)
    assert found is not None
    name_at = blob.find(FAMILY.encode("utf-16-be"))
    distance = name_at - found.offset
    assert 0 < distance < len(blob)
    assert find_embedded_font(blob, FAMILY, window=distance - 1) is None
    assert find_embedded_font(blob, FAMILY, window=distance) is not None


def test_the_real_family_name_is_the_one_the_client_embeds() -> None:
    # Recorded from the game PC's sharedassets0.assets: 'VIPER NORA', with the copyright
    # line 'Dimitris K. - pOPdOG fONTS 1999' beside it.
    assert FONT_FAMILY == "VIPER NORA"


def test_a_truncated_table_is_not_mistaken_for_a_font() -> None:
    font = build_font()
    for cut in (4, 20, len(font) - 8):
        assert table_directory(font[:cut], 0) is None
