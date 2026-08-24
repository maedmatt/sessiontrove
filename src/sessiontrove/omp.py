"""Read archived OMP sessions.

OMP (Oh My Pi) is a Pi fork that keeps Pi's session format and adds
session titles, which the Pi core already understands. This reader is
the Pi reader pointed at the OMP store.
"""

from pathlib import Path

from . import pi


def find(root: Path) -> list[tuple[dict, Path]]:
    """Return (summary, path) pairs for OMP sessions in an archive."""

    return pi.scan(root, "omp", ("omp", "sessions"))


def parse(path: Path) -> dict:
    """Parse one OMP session file into neutral viewer records."""

    return pi.parse(path) | {"agent": "omp"}
