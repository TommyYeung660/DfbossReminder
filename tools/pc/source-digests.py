"""Print a digest of every source file, so a copy of this tree can be proven identical.

The game PC's checkout is not a git clone - it is a directory that gets files copied into
it - so "is the code over there the code over here?" has no built-in answer, and the answer
has been wrong before: a stale file was built into a Desktop exe, and the only symptom was a
button raising an error inside a Tk callback that swallowed it.

Two runs of this, one on each machine, are comparable line for line:

    python3 tools/pc/source-digests.py            # here
    py -3 tools\\pc\\source-digests.py             # there

The digest covers ``src``, ``tools`` and ``tests``: everything that ends up inside the exe or
runs against it. ``__pycache__`` and build output are skipped, because they differ by
machine for reasons that have nothing to do with the source.

Usage (either machine, from the project root):
    py -3 tools\\pc\\source-digests.py
    py -3 tools\\pc\\source-digests.py --check other.txt
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TREES = ("src", "tools", "tests")
SUFFIXES = (".py", ".cmd", ".ps1", ".sh")
SKIP = ("__pycache__", "evidence", "build", "dist")


def digests() -> list[str]:
    lines: list[str] = []
    for tree in TREES:
        root = PROJECT_ROOT / tree
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            relative = path.relative_to(PROJECT_ROOT).as_posix()
            if any(part in SKIP for part in path.parts):
                continue
            lines.append(f"{hashlib.md5(path.read_bytes()).hexdigest()}  {relative}")
    return sorted(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", default="",
                        help="compare against a digest file written by the other machine")
    parser.add_argument("--write", default="", help="write the list here as well")
    args = parser.parse_args()

    lines = digests()
    for line in lines:
        print(line)
    if args.write:
        Path(args.write).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nwritten to {args.write}")

    if args.check:
        other = Path(args.check).read_text(encoding="utf-8").splitlines()
        mine, theirs = set(line.strip() for line in lines), set(line.strip() for line in other)
        only_here = sorted(mine - theirs)
        only_there = sorted(theirs - mine)
        print(f"\ncompared with {args.check}: {len(mine)} file(s) here, {len(theirs)} there")
        if not only_here and not only_there:
            print("IN SYNC: every source file is byte-identical on both machines")
            return 0
        for line in only_here:
            print(f"  only here:  {line}")
        for line in only_there:
            print(f"  only there: {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
