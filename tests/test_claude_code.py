import json
from pathlib import Path

from sessiontrove import claude_code


def record(kind: str, uuid: str, parent: str | None, **extra) -> dict:
    return {
        "type": kind,
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-08-20T10:00:00.000Z",
        "cwd": "/home/user/project",
        "version": "2.0.0",
        **extra,
    }


def write(path: Path, records: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [line if isinstance(line, str) else json.dumps(line) for line in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_find_discovers_sessions_with_titles_and_previews(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    session = root / "mac/claude-code/projects/proj/abc.jsonl"
    write(
        session,
        [
            {"type": "mode", "mode": "default", "sessionId": "sess-1"},
            record(
                "user",
                "u1",
                None,
                message={
                    "role": "user",
                    "content": "<command-name>/clear</command-name>",
                },
            ),
            record(
                "user",
                "u2",
                "u1",
                message={"role": "user", "content": "  hello   claude  "},
            ),
            {"type": "ai-title", "aiTitle": "Fix the parser", "sessionId": "sess-1"},
        ],
    )
    write(root / "mac/claude-code/history.jsonl", [{"display": "prompt"}])
    subagent = root / "mac/claude-code/projects/proj/abc/subagents/agent-x.jsonl"
    write(
        subagent, [record("user", "s1", None, message={"role": "user", "content": "x"})]
    )
    outside = tmp_path / "outside.jsonl"
    write(
        outside, [record("user", "o1", None, message={"role": "user", "content": "x"})]
    )
    (root / "mac/claude-code/projects/proj/link.jsonl").symlink_to(outside)

    found = claude_code.find(root)

    assert [summary["id"] for summary, _ in found] == [
        "mac/claude-code/projects/proj/abc.jsonl"
    ]
    summary = found[0][0]
    assert summary["agent"] == "claude-code"
    assert summary["machine"] == "mac"
    assert summary["cwd"] == "/home/user/project"
    assert summary["title"] == "Fix the parser"
    assert summary["preview"] == "hello claude"


def test_parse_maps_messages_tools_and_system_records(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    write(
        session,
        [
            {"type": "file-history-snapshot", "messageId": "m", "snapshot": {}},
            record("user", "a", None, message={"role": "user", "content": "run ls"}),
            record(
                "assistant",
                "b",
                "a",
                message={
                    "role": "assistant",
                    "model": "claude-fable-5",
                    "usage": {"input_tokens": 10},
                    "content": [
                        {"type": "thinking", "thinking": "planning"},
                        {"type": "text", "text": "Listing."},
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        },
                    ],
                },
            ),
            record(
                "system",
                "noise",
                "b",
                subtype="turn_duration",
                durationMs=5,
            ),
            record(
                "user",
                "c",
                "noise",
                message={
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "is_error": False,
                            "content": [
                                {"type": "text", "text": "a.txt"},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": "aGk=",
                                    },
                                },
                            ],
                        }
                    ],
                },
            ),
            record(
                "system",
                "d",
                "c",
                subtype="compact_boundary",
                content="Conversation compacted",
                compactMetadata={"preTokens": 84000},
            ),
            record("mystery", "e", "d", payload=[1]),
        ],
    )

    parsed = claude_code.parse(session)

    assert parsed["agent"] == "claude-code"
    assert parsed["meta"]["session_id"] == "sess-1"
    assert parsed["meta"]["cwd"] == "/home/user/project"
    kinds = [entry["kind"] for entry in parsed["records"]]
    assert kinds == ["user", "assistant", "tool_result", "compaction", "unknown"]

    user, assistant, result, compaction, unknown = parsed["records"]
    assert user["parts"] == [{"type": "text", "text": "run ls"}]
    assert assistant["model"] == "claude-fable-5"
    assert assistant["parts"][2] == {
        "type": "tool_call",
        "name": "Bash",
        "arguments": {"command": "ls"},
    }
    assert result["toolName"] == "Bash"
    assert result["isError"] is False
    assert result["parts"] == [
        {"type": "text", "text": "a.txt"},
        {"type": "image", "mimeType": "image/png", "data": "aGk="},
    ]
    assert result["parentId"] == "b", "skipped records must not break the chain"
    assert compaction["tokensBefore"] == 84000
    assert unknown["raw"]["type"] == "mystery"


def test_parse_skips_sidechains_and_keeps_bad_lines(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    write(
        session,
        [
            record("user", "a", None, message={"role": "user", "content": "hi"}),
            record(
                "user",
                "side",
                None,
                isSidechain=True,
                message={"role": "user", "content": "subagent"},
            ),
            "not json at all",
        ],
    )

    parsed = claude_code.parse(session)

    kinds = [entry["kind"] for entry in parsed["records"]]
    assert kinds == ["user", "unknown"]
    assert parsed["records"][1]["raw"] == "not json at all"
