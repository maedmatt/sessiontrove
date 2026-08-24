"""Read archived Claude Code sessions.

Same reader interface as the Pi module: ``find(root)`` returns
``(summary, path)`` pairs and ``parse(path)`` returns neutral viewer
records. Claude Code transcripts live under
``claude-code/projects/<project>/<session>.jsonl`` and form a branch
tree through ``uuid``/``parentUuid``. App-state records are skipped, but
their ids are redirected so parent chains stay intact.
"""

import json
import os
from pathlib import Path

_SUMMARY_LINES = 300
_PREVIEW_CHARS = 160

_NOISE = {
    "mode",
    "permission-mode",
    "file-history-snapshot",
    "file-history-delta",
    "attachment",
    "last-prompt",
    "queue-operation",
    "atis-latch",
    "agent-name",
    "agent-color",
    "ai-title",
    "custom-title",
    "summary",
}


def find(root: Path) -> list[tuple[dict, Path]]:
    """Return (summary, path) pairs for Claude Code sessions."""

    root = Path(os.path.abspath(root))
    found = []
    for base in _bases(root):
        projects = base / "claude-code" / "projects"
        if (base / "claude-code").is_symlink() or projects.is_symlink():
            continue
        if not projects.is_dir():
            continue
        for path in _session_files(projects):
            summary = _summary(path)
            if summary is None:
                continue
            summary["agent"] = "claude-code"
            summary["machine"] = base.name if base != root else ""
            summary["id"] = path.relative_to(root).as_posix()
            found.append((summary, path))
    return found


def parse(path: Path) -> dict:
    """Parse one Claude Code session file into neutral viewer records."""

    meta: dict = {}
    title = None
    records: list[dict] = []
    redirect: dict = {}
    tool_names: dict = {}
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
            title = _title(record) or title
            if not meta and record.get("sessionId") and record.get("uuid"):
                meta = {
                    "session_id": record.get("sessionId"),
                    "started": record.get("timestamp"),
                    "cwd": record.get("cwd"),
                    "version": record.get("version"),
                }
            parent = record.get("parentUuid")
            while parent in redirect:
                parent = redirect[parent]
            if _skipped(record):
                if record.get("uuid"):
                    redirect[record["uuid"]] = parent
                continue
            entry = _entry(record, tool_names)
            entry["id"] = str(record.get("uuid") or f"line-{number}")
            entry["parentId"] = parent if "parentUuid" in record else last_id
            entry["timestamp"] = record.get("timestamp")
            records.append(entry)
            last_id = entry["id"]
    if title:
        meta["title"] = title
    return {"agent": "claude-code", "meta": meta, "records": records}


def _bases(root: Path) -> list[Path]:
    bases = [root]
    if root.is_dir():
        bases += sorted(
            child
            for child in root.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
    return bases


def _session_files(projects: Path) -> list[Path]:
    files = []
    for project in sorted(projects.iterdir()):
        if project.is_symlink() or not project.is_dir():
            continue
        for path in sorted(project.iterdir()):
            if (
                path.name.endswith(".jsonl")
                and not path.is_symlink()
                and path.is_file()
            ):
                files.append(path)
    return files


def _summary(path: Path) -> dict | None:
    cwd = started = title = None
    preview = ""
    seen_transcript = False
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, start=1):
                if number > _SUMMARY_LINES or (preview and title):
                    break
                record = _json_line(line)
                if record is None:
                    continue
                title = _title(record) or title
                if not record.get("sessionId") or not record.get("uuid"):
                    continue
                seen_transcript = True
                cwd = cwd or record.get("cwd")
                started = started or record.get("timestamp")
                if not preview and record.get("type") == "user":
                    preview = _preview(record)
        size = path.stat().st_size
    except OSError:
        return None
    if not seen_transcript:
        return None
    return {
        "name": path.stem,
        "cwd": cwd,
        "started": started,
        "title": title,
        "preview": preview,
        "size": size,
    }


def _preview(record: dict) -> str:
    message = record.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    texts = [content] if isinstance(content, str) else []
    if isinstance(content, list):
        texts = [
            part.get("text")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
    for text in texts:
        text = " ".join(text.split())
        if text and not text.startswith("<") and not text.startswith("Caveat:"):
            return text[:_PREVIEW_CHARS]
    return ""


def _title(record: dict) -> str | None:
    kind = record.get("type")
    if kind == "custom-title":
        return record.get("customTitle")
    if kind == "ai-title":
        return record.get("aiTitle")
    if kind == "summary":
        return record.get("summary")
    return None


def _skipped(record: dict) -> bool:
    if record.get("type") in _NOISE:
        return True
    if record.get("isSidechain") is True or record.get("isMeta") is True:
        return True
    return record.get("type") == "system" and record.get("subtype") == "turn_duration"


def _json_line(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _entry(record: dict, tool_names: dict) -> dict:
    kind = record.get("type")
    if kind in ("user", "assistant"):
        return _message(record, tool_names)
    if kind == "system":
        if record.get("subtype") == "compact_boundary":
            compact = record.get("compactMetadata")
            tokens = compact.get("preTokens") if isinstance(compact, dict) else None
            return {
                "kind": "compaction",
                "summary": record.get("content"),
                "tokensBefore": tokens,
            }
        return {
            "kind": "custom",
            "customType": record.get("subtype") or "system",
            "raw": record.get("content"),
        }
    return {"kind": "unknown", "raw": record}


def _message(record: dict, tool_names: dict) -> dict:
    message = record.get("message")
    if not isinstance(message, dict):
        return {"kind": "unknown", "raw": record}
    content = message.get("content")
    blocks = content if isinstance(content, list) else []
    if isinstance(content, str):
        blocks = [{"type": "text", "text": content}]
    if record.get("type") == "assistant":
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_names[block.get("id")] = block.get("name")
        return {
            "kind": "assistant",
            "model": message.get("model"),
            "stopReason": message.get("stop_reason"),
            "usage": message.get("usage"),
            "parts": [_part(block) for block in blocks],
        }
    results = [
        block
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    if results:
        parts = []
        for block in blocks:
            if block in results:
                parts += _result_parts(block)
            else:
                parts.append(_part(block))
        return {
            "kind": "tool_result",
            "toolName": tool_names.get(results[0].get("tool_use_id")),
            "isError": any(block.get("is_error") for block in results),
            "parts": parts,
        }
    return {"kind": "user", "parts": [_part(block) for block in blocks]}


def _result_parts(block: dict) -> list[dict]:
    content = block.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [_part(inner) for inner in content]
    return []


def _part(block) -> dict:
    if not isinstance(block, dict):
        return {"type": "unknown", "raw": block}
    kind = block.get("type")
    if kind == "text":
        return {"type": "text", "text": block.get("text")}
    if kind == "thinking":
        return {"type": "thinking", "text": block.get("thinking")}
    if kind == "tool_use":
        return {
            "type": "tool_call",
            "name": block.get("name"),
            "arguments": block.get("input"),
        }
    if kind == "image":
        source = block.get("source")
        if isinstance(source, dict) and source.get("type") == "base64":
            return {
                "type": "image",
                "mimeType": source.get("media_type"),
                "data": source.get("data"),
            }
    return {"type": "unknown", "raw": block}
