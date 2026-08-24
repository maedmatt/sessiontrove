"""Read archived Pi sessions.

This module is the Pi reader and the shared core for agents that store
Pi-format sessions (OMP, OpenClaw). Readers offer the same two functions
so the viewer stays agent-neutral: ``find(root)`` returns
``(summary, path)`` pairs for every session in an archive, and
``parse(path)`` turns one session file into the record structure the
viewer renders. Both only read.
"""

import json
import os
from pathlib import Path

_LINE_LIMIT = 65536
_PREVIEW_RECORDS = 50
_PREVIEW_CHARS = 160


def find(root: Path) -> list[tuple[dict, Path]]:
    """Return (summary, path) pairs for Pi sessions under an archive root.

    The root may be the archive itself, holding one directory per machine,
    or a single machine directory. Symlinks are never followed.
    """

    return scan(root, "pi", ("pi", "sessions"))


def scan(root: Path, agent: str, parts: tuple[str, ...]) -> list[tuple[dict, Path]]:
    """Discover Pi-format sessions in one store below each machine."""

    root = Path(os.path.abspath(root))
    found = []
    for base in bases(root):
        directory = base
        symlinked = False
        for part in parts:
            directory = directory / part
            if directory.is_symlink():
                symlinked = True
                break
        if symlinked or not directory.is_dir():
            continue
        machine = base.name if base != root else ""
        found += scan_directory(directory, root, agent, machine)
    return found


def scan_directory(
    directory: Path, root: Path, agent: str, machine: str
) -> list[tuple[dict, Path]]:
    """List the Pi-format sessions inside one directory tree."""

    found = []
    for path in _session_files(directory):
        summary = _summary(path)
        if summary is None:
            continue
        summary["agent"] = agent
        summary["machine"] = machine
        summary["id"] = path.relative_to(root).as_posix()
        found.append((summary, path))
    return found


def parse(path: Path) -> dict:
    """Parse one Pi session file into neutral viewer records."""

    meta: dict = {}
    records: list[dict] = []
    last_id = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = _json_line(line)
            if record is None:
                records.append(
                    {
                        "id": f"line-{number}",
                        "parentId": last_id,
                        "timestamp": None,
                        "kind": "unknown",
                        "raw": line,
                    }
                )
                last_id = f"line-{number}"
                continue
            if record.get("type") == "title":
                meta["title"] = record.get("title") or meta.get("title")
                continue
            if record.get("type") == "title_change" and record.get("title"):
                meta["title"] = record["title"]
            if record.get("type") == "session" and "session_id" not in meta:
                meta.update(
                    session_id=record.get("id"),
                    started=record.get("timestamp"),
                    cwd=record.get("cwd"),
                    version=record.get("version"),
                )
                if record.get("title"):
                    meta["title"] = record["title"]
                continue
            entry = _entry(record, number, last_id)
            records.append(entry)
            last_id = entry["id"]
    return {"agent": "pi", "meta": meta, "records": records}


def bases(root: Path) -> list[Path]:
    """The archive root plus its machine directories."""

    found = [root]
    if root.is_dir():
        found += sorted(
            child
            for child in root.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
    return found


def _session_files(sessions: Path) -> list[Path]:
    files = []
    for directory, names, filenames in os.walk(sessions, followlinks=False):
        current = Path(directory)
        names[:] = sorted(name for name in names if not (current / name).is_symlink())
        for filename in sorted(filenames):
            path = current / filename
            if filename.endswith(".jsonl") and not path.is_symlink() and path.is_file():
                files.append(path)
    return files


def _summary(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            header, title = _header(handle)
            if header is None:
                return None
            preview = _preview(handle)
        size = path.stat().st_size
    except OSError:
        return None
    if preview is None:
        return None
    return {
        "name": path.stem,
        "session_id": header.get("id"),
        "cwd": header.get("cwd"),
        "started": header.get("timestamp"),
        "title": title,
        "preview": preview,
        "size": size,
    }


def _header(handle) -> tuple[dict | None, str | None]:
    """Find the session header, tolerating OMP's leading title record."""

    title = None
    for _ in range(4):
        record = _json_line(handle.readline(_LINE_LIMIT))
        if record is None:
            return None, None
        if record.get("type") == "title":
            title = record.get("title") or title
            continue
        if record.get("type") == "session":
            return record, record.get("title") or title
        return None, None
    return None, None


def _preview(handle) -> str | None:
    """First user text, or None for a spawned subagent's task session."""

    for _ in range(_PREVIEW_RECORDS):
        line = handle.readline(_LINE_LIMIT)
        if not line:
            break
        record = _json_line(line)
        if record is None:
            continue
        if record.get("type") == "session_init":
            return None
        if record.get("type") != "message":
            continue
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        texts = [
            part.get("text")
            for part in _parts(message.get("content"))
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        text = " ".join(" ".join(filter(None, texts)).split())
        if text:
            return text[:_PREVIEW_CHARS]
    return ""


def _json_line(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _entry(record: dict, number: int, last_id: str | None) -> dict:
    base = {
        "id": str(record.get("id") or f"line-{number}"),
        "parentId": record.get("parentId", last_id),
        "timestamp": record.get("timestamp"),
    }
    kind = record.get("type")
    if kind == "message":
        return base | _message(record)
    if kind == "model_change":
        return base | {
            "kind": "model_change",
            "provider": record.get("provider"),
            "model": record.get("modelId") or record.get("model"),
        }
    if kind == "thinking_level_change":
        return base | {"kind": "thinking_level", "level": record.get("thinkingLevel")}
    if kind == "title_change":
        return base | {
            "kind": "custom",
            "customType": "title",
            "raw": record.get("title"),
        }
    if kind == "custom_message":
        return base | {
            "kind": "custom",
            "customType": record.get("customType") or "message",
            "raw": record.get("content") or record.get("details"),
        }
    if kind == "session_init":
        return base | {
            "kind": "custom",
            "customType": "session_init",
            "raw": {"task": record.get("task"), "tools": record.get("tools")},
        }
    if kind == "compaction":
        return base | {
            "kind": "compaction",
            "summary": record.get("summary"),
            "tokensBefore": record.get("tokensBefore"),
        }
    if kind == "custom":
        return base | {
            "kind": "custom",
            "customType": record.get("customType"),
            "raw": record.get("data"),
        }
    return base | {"kind": "unknown", "raw": record}


def _message(record: dict) -> dict:
    message = record.get("message")
    if not isinstance(message, dict):
        return {"kind": "unknown", "raw": record}
    role = message.get("role")
    parts = [_part(part) for part in _parts(message.get("content"))]
    if role == "user":
        return {"kind": "user", "parts": parts}
    if role == "assistant":
        return {
            "kind": "assistant",
            "model": message.get("model"),
            "stopReason": message.get("stopReason"),
            "usage": message.get("usage"),
            "parts": parts,
        }
    if role == "toolResult":
        return {
            "kind": "tool_result",
            "toolName": message.get("toolName"),
            "isError": bool(message.get("isError")),
            "parts": parts,
        }
    return {"kind": "unknown", "raw": record}


def _parts(content) -> list:
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _part(part) -> dict:
    if not isinstance(part, dict):
        return {"type": "unknown", "raw": part}
    kind = part.get("type")
    if kind == "text":
        return {"type": "text", "text": part.get("text")}
    if kind == "thinking":
        return {"type": "thinking", "text": part.get("thinking")}
    if kind == "toolCall":
        return {
            "type": "tool_call",
            "name": part.get("name"),
            "arguments": part.get("arguments"),
        }
    if kind == "image":
        return {
            "type": "image",
            "mimeType": part.get("mimeType"),
            "data": part.get("data"),
        }
    return {"type": "unknown", "raw": part}
