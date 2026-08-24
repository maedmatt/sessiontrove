"""Read archived OpenClaw sessions.

OpenClaw stores Pi-format sessions per agent persona under
``openclaw/agents/<name>/sessions``. Trajectory logs and migration
artifacts living in the same directories lack the Pi session header and
are skipped by the shared core. Each persona's ``sessions.json`` index
labels some sessions; the persona name is the fallback title.
"""

import json
import os
from pathlib import Path

from . import pi


def find(root: Path) -> list[tuple[dict, Path]]:
    """Return (summary, path) pairs for OpenClaw sessions in an archive."""

    root = Path(os.path.abspath(root))
    found = []
    for base in pi.bases(root):
        agents = base / "openclaw" / "agents"
        if (base / "openclaw").is_symlink() or agents.is_symlink():
            continue
        if not agents.is_dir():
            continue
        machine = base.name if base != root else ""
        for persona in sorted(agents.iterdir()):
            sessions = persona / "sessions"
            if persona.is_symlink() or sessions.is_symlink():
                continue
            if not persona.is_dir() or not sessions.is_dir():
                continue
            labels = _labels(sessions / "sessions.json")
            for summary, path in pi.scan_directory(sessions, root, "openclaw", machine):
                summary["title"] = (
                    summary.get("title")
                    or labels.get(summary.get("session_id"))
                    or persona.name
                )
                found.append((summary, path))
    return found


def parse(path: Path) -> dict:
    """Parse one OpenClaw session file into neutral viewer records."""

    return pi.parse(path) | {"agent": "openclaw"}


def _labels(path: Path) -> dict:
    """Session labels from a persona's sessions.json index."""

    if path.is_symlink() or not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            index = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    labels = {}
    if isinstance(index, dict):
        for value in index.values():
            if (
                isinstance(value, dict)
                and value.get("sessionId")
                and value.get("label")
            ):
                labels[value["sessionId"]] = value["label"]
    return labels
