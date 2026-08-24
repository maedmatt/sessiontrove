"""Read archived OpenClaw sessions.

OpenClaw stores Pi-format sessions per agent persona under
``openclaw/agents/<name>/sessions``. Trajectory logs and migration
artifacts living in the same directories lack the Pi session header and
are skipped by the shared core. Each persona's ``sessions.json`` index
labels some sessions; the persona name is the fallback title.
Machine-initiated sessions (heartbeat polls, cron jobs, supervisor
wakes, control-plane tasks) are hidden, and user messages that OpenClaw
wrote twice on delivery retries are collapsed to one.
"""

import json
import os
from pathlib import Path

from . import pi

_MACHINE_PREFIXES = (
    "[OpenClaw heartbeat poll]",
    "[cron:",
    "[SUPERVISOR",
    "Control-plane task id:",
)


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
                preview = summary.get("preview", "")
                if preview.startswith(_MACHINE_PREFIXES):
                    continue
                summary["title"] = (
                    summary.get("title")
                    or labels.get(summary.get("session_id"))
                    or persona.name
                )
                found.append((summary, path))
    return found


def parse(path: Path) -> dict:
    """Parse one OpenClaw session file into neutral viewer records."""

    parsed = pi.parse(path) | {"agent": "openclaw"}
    duplicates = _duplicates(path)
    if duplicates:
        redirect: dict = {}
        records = []
        for record in parsed["records"]:
            parent = record.get("parentId")
            while parent in redirect:
                parent = redirect[parent]
            record["parentId"] = parent
            if record["id"] in duplicates:
                redirect[record["id"]] = parent
                continue
            records.append(record)
        parsed["records"] = records
    return parsed


def _duplicates(path: Path) -> set:
    """Ids of user messages OpenClaw wrote twice on delivery retries."""

    seen: set = set()
    duplicates: set = set()
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "message":
                    continue
                message = record.get("message")
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                key = message.get("idempotencyKey")
                if not key:
                    continue
                if key in seen:
                    duplicates.add(str(record.get("id")))
                else:
                    seen.add(key)
    except OSError:
        pass
    return duplicates


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
