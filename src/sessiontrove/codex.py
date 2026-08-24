"""Read archived Codex sessions.

Same reader interface as the other modules: ``find(root)`` returns
``(summary, path)`` pairs and ``parse(path)`` returns neutral viewer
records. Codex rollouts are linear envelopes ``{timestamp, type,
payload}``; many things appear twice (``response_item`` mirrors
``event_msg``), so text comes from ``event_msg`` and reasoning and tool
traffic from ``response_item``.
"""

import json
import os
from pathlib import Path

_LINE_LIMIT = 65536
_PREVIEW_RECORDS = 50
_PREVIEW_CHARS = 160

_ROOTS = (Path("sessions"), Path("archived_sessions"))
_SKIPPED_EVENTS = {
    "token_count",
    "task_started",
    "task_complete",
    "agent_reasoning",
    "agent_reasoning_delta",
    "agent_reasoning_section_break",
    "context_compacted",
    "thread_settings_applied",
    "sub_agent_activity",
    "web_search_end",
    "patch_apply_end",
    "mcp_tool_call_end",
    "image_generation_end",
}
_SKIPPED_ITEMS = {"message", "ghost_snapshot"}
_SKIPPED_RECORDS = {"world_state", "inter_agent_communication_metadata"}


def find(root: Path) -> list[tuple[dict, Path]]:
    """Return (summary, path) pairs for Codex rollouts in an archive."""

    root = Path(os.path.abspath(root))
    found = []
    for base in _bases(root):
        codex = base / "codex"
        if codex.is_symlink():
            continue
        for store in _ROOTS:
            directory = codex / store
            if directory.is_symlink() or not directory.is_dir():
                continue
            for path in _session_files(directory):
                summary = _summary(path)
                if summary is None:
                    continue
                summary["agent"] = "codex"
                summary["machine"] = base.name if base != root else ""
                summary["id"] = path.relative_to(root).as_posix()
                found.append((summary, path))
    return found


def parse(path: Path) -> dict:
    """Parse one Codex rollout file into neutral viewer records."""

    meta: dict = {}
    records: list[dict] = []
    tool_names: dict = {}
    context = {"model": None, "effort": None}
    last_id = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = _json_line(line)
            entries: list[dict]
            if record is None:
                entries = [{"kind": "unknown", "raw": line}]
            elif record.get("type") == "session_meta" and not meta:
                payload = record.get("payload") or {}
                meta = {
                    "session_id": payload.get("id"),
                    "started": payload.get("timestamp") or record.get("timestamp"),
                    "cwd": payload.get("cwd"),
                }
                continue
            else:
                entries = _entries(record, tool_names, context)
            for offset, entry in enumerate(entries):
                suffix = "" if len(entries) == 1 else f"-{offset}"
                entry["id"] = f"line-{number}{suffix}"
                entry["parentId"] = last_id
                entry.setdefault(
                    "timestamp", record.get("timestamp") if record else None
                )
                records.append(entry)
                last_id = entry["id"]
    return {"agent": "codex", "meta": meta, "records": records}


def _bases(root: Path) -> list[Path]:
    bases = [root]
    if root.is_dir():
        bases += sorted(
            child
            for child in root.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
    return bases


def _session_files(directory: Path) -> list[Path]:
    files = []
    for current, names, filenames in os.walk(directory, followlinks=False):
        parent = Path(current)
        names[:] = sorted(n for n in names if not (parent / n).is_symlink())
        for filename in sorted(filenames):
            path = parent / filename
            if filename.endswith(".jsonl") and not path.is_symlink() and path.is_file():
                files.append(path)
    return files


def _summary(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            header = _json_line(handle.readline(_LINE_LIMIT))
            if header is None or header.get("type") != "session_meta":
                return None
            payload = header.get("payload") or {}
            if isinstance(payload.get("source"), dict):
                return None  # spawned subagent or auto-review run, not a chat
            preview = _preview(handle)
        size = path.stat().st_size
    except OSError:
        return None
    return {
        "name": path.stem,
        "cwd": payload.get("cwd"),
        "started": payload.get("timestamp") or header.get("timestamp"),
        "preview": preview,
        "size": size,
    }


def _preview(handle) -> str:
    for _ in range(_PREVIEW_RECORDS):
        line = handle.readline(_LINE_LIMIT)
        if not line:
            break
        record = _json_line(line)
        if record is None or record.get("type") != "event_msg":
            continue
        payload = record.get("payload") or {}
        if payload.get("type") != "user_message":
            continue
        text = " ".join(str(payload.get("message") or "").split())
        if text and not text.startswith("<"):
            return text[:_PREVIEW_CHARS]
    return ""


def _json_line(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _entries(record: dict, tool_names: dict, context: dict) -> list[dict]:
    """Map one envelope to zero or more neutral records."""

    kind = record.get("type")
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    if kind == "event_msg":
        return _event(payload, context)
    if kind == "response_item":
        return _item(payload, tool_names, context)
    if kind == "turn_context":
        return _turn_context(payload, context)
    if kind == "compacted":
        return [{"kind": "compaction", "summary": payload.get("message")}]
    if kind in _SKIPPED_RECORDS:
        return []
    return [{"kind": "unknown", "raw": record}]


def _event(payload: dict, context: dict) -> list[dict]:
    kind = payload.get("type")
    if kind == "user_message":
        text = payload.get("message")
        return [{"kind": "user", "parts": [{"type": "text", "text": text}]}]
    if kind == "agent_message":
        return [
            {
                "kind": "assistant",
                "model": context["model"],
                "parts": [{"type": "text", "text": payload.get("message")}],
            }
        ]
    if kind in _SKIPPED_EVENTS:
        return []
    return [{"kind": "custom", "customType": kind, "raw": payload}]


def _item(payload: dict, tool_names: dict, context: dict) -> list[dict]:
    kind = payload.get("type")
    model = context["model"]
    if kind == "reasoning":
        summary = payload.get("summary")
        parts = [
            {"type": "thinking", "text": part.get("text")}
            for part in (summary if isinstance(summary, list) else [])
            if isinstance(part, dict) and part.get("text")
        ]
        return [{"kind": "assistant", "model": model, "parts": parts}] if parts else []
    if kind in ("function_call", "custom_tool_call"):
        tool_names[payload.get("call_id")] = payload.get("name")
        call = {
            "type": "tool_call",
            "name": payload.get("name"),
            "arguments": payload.get("arguments") or payload.get("input"),
        }
        return [{"kind": "assistant", "model": model, "parts": [call]}]
    if kind in ("function_call_output", "custom_tool_call_output"):
        text, error = _output(payload.get("output"))
        return [
            {
                "kind": "tool_result",
                "toolName": tool_names.get(payload.get("call_id")),
                "isError": error,
                "parts": [{"type": "text", "text": text}],
            }
        ]
    if kind == "web_search_call":
        call = {
            "type": "tool_call",
            "name": "web_search",
            "arguments": payload.get("action"),
        }
        return [{"kind": "assistant", "model": model, "parts": [call]}]
    if kind == "tool_search_call":
        tool_names[payload.get("call_id")] = "tool_search"
        call = {
            "type": "tool_call",
            "name": "tool_search",
            "arguments": payload.get("arguments"),
        }
        return [{"kind": "assistant", "model": model, "parts": [call]}]
    if kind == "tool_search_output":
        text = json.dumps(payload.get("tools"), indent=2)
        return [
            {
                "kind": "tool_result",
                "toolName": tool_names.get(payload.get("call_id")),
                "isError": False,
                "parts": [{"type": "text", "text": text}],
            }
        ]
    if kind == "agent_message":
        return [{"kind": "custom", "customType": "inter-agent message", "raw": payload}]
    if kind in _SKIPPED_ITEMS:
        return []
    return [{"kind": "unknown", "raw": payload}]


def _output(output) -> tuple[str, bool]:
    """Unwrap a tool output that may be a JSON envelope with metadata."""

    if not isinstance(output, str):
        return json.dumps(output, indent=2), False
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return output, False
    if isinstance(parsed, dict) and "output" in parsed:
        metadata = parsed.get("metadata")
        code = metadata.get("exit_code") if isinstance(metadata, dict) else 0
        return str(parsed.get("output") or ""), bool(code)
    return output, False


def _turn_context(payload: dict, context: dict) -> list[dict]:
    entries = []
    model = payload.get("model")
    effort = payload.get("effort")
    if model and model != context["model"]:
        entries.append({"kind": "model_change", "provider": "codex", "model": model})
        context["model"] = model
    if effort and effort != context["effort"]:
        entries.append({"kind": "thinking_level", "level": effort})
        context["effort"] = effort
    return entries
