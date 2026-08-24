"""Sessiontrove command-line interface."""

import argparse
import sqlite3
import sys
from pathlib import Path

from .archive import archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive local coding-agent sessions without changing the originals."
    )
    parser.add_argument("destination", type=Path, help="private archive directory")
    args = parser.parse_args(argv)

    try:
        results = archive(args.destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if not results:
        print("error: no supported session stores found", file=sys.stderr)
        return 1
    for agent, updated in sorted(results.items()):
        print(f"{agent}: {updated} files updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
