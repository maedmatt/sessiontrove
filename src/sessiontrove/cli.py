"""Sessiontrove command-line interface."""

import argparse
import sys
from pathlib import Path

from .archive import archive
from .viewer import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sessiontrove",
        description="Archive and view local coding-agent sessions.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    archiver = commands.add_parser(
        "archive",
        help="copy local sessions into a private archive without changing them",
    )
    archiver.add_argument(
        "destination", type=Path, help="private shared archive directory"
    )
    archiver.add_argument(
        "--machine",
        required=True,
        help="stable name for this machine, such as macbookpro-m4",
    )

    viewer = commands.add_parser(
        "view", help="browse an archive read-only in the browser"
    )
    viewer.add_argument("archive", type=Path, help="archive directory to view")
    viewer.add_argument(
        "--port", type=int, default=0, help="port on 127.0.0.1 (default: automatic)"
    )
    viewer.add_argument(
        "--no-browser", action="store_true", help="do not open the browser"
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "archive":
            return _archive(args.destination, args.machine)
        return _view(args.archive, args.port, not args.no_browser)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _archive(destination: Path, machine: str) -> int:
    results = archive(destination, machine)
    if not results:
        print("error: no supported session stores found", file=sys.stderr)
        return 1
    for agent, updated in sorted(results.items()):
        print(f"{agent}: {updated} files updated")
    return 0


def _view(root: Path, port: int, open_browser: bool) -> int:
    if not root.is_dir():
        print(f"error: {root} is not a directory", file=sys.stderr)
        return 1
    return serve(root, port, open_browser)


if __name__ == "__main__":
    raise SystemExit(main())
