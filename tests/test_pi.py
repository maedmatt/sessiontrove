import json
from pathlib import Path

from sessiontrove import pi

HEADER = {
    "type": "session",
    "version": 3,
    "id": "sess-1",
    "timestamp": "2026-08-20T10:00:00.000Z",
    "cwd": "/home/user/project",
}


def write_session(path: Path, records: list, header: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(header or HEADER)]
    lines += [
        record if isinstance(record, str) else json.dumps(record) for record in records
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def message(id: str, parent: str | None, role: str, content: list, **extra) -> dict:
    return {
        "type": "message",
        "id": id,
        "parentId": parent,
        "timestamp": "2026-08-20T10:01:00.000Z",
        "message": {"role": role, "content": content, **extra},
    }


def test_find_discovers_archived_sessions_per_machine(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    write_session(
        root / "mac/pi/sessions/project/a.jsonl",
        [message("m1", None, "user", [{"type": "text", "text": "  hello \n viewer "}])],
    )
    write_session(root / "linux/pi/sessions/b.jsonl", [])
    other = root / "mac/codex/sessions/c.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text(json.dumps(HEADER) + "\n", encoding="utf-8")
    (root / "mac/pi/sessions/notes.txt").write_text("not a session", encoding="utf-8")
    (root / "mac/pi/sessions/broken.jsonl").write_text("not json\n", encoding="utf-8")
    outside = tmp_path / "outside.jsonl"
    write_session(outside, [])
    (root / "mac/pi/sessions/link.jsonl").symlink_to(outside)

    found = pi.find(root)

    assert [summary["id"] for summary, _ in found] == [
        "linux/pi/sessions/b.jsonl",
        "mac/pi/sessions/project/a.jsonl",
    ]
    summary, path = found[1]
    assert path == root / "mac/pi/sessions/project/a.jsonl"
    assert summary["agent"] == "pi"
    assert summary["machine"] == "mac"
    assert summary["cwd"] == "/home/user/project"
    assert summary["started"] == "2026-08-20T10:00:00.000Z"
    assert summary["preview"] == "hello viewer"


def test_find_accepts_a_single_machine_directory(tmp_path: Path) -> None:
    write_session(tmp_path / "pi/sessions/a.jsonl", [])

    found = pi.find(tmp_path)

    assert [(summary["id"], summary["machine"]) for summary, _ in found] == [
        ("pi/sessions/a.jsonl", "")
    ]


def test_parse_normalizes_known_records(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    write_session(
        session,
        [
            {
                "type": "model_change",
                "id": "a",
                "parentId": None,
                "timestamp": "t1",
                "provider": "anthropic",
                "modelId": "claude",
            },
            {
                "type": "thinking_level_change",
                "id": "b",
                "parentId": "a",
                "timestamp": "t2",
                "thinkingLevel": "high",
            },
            message("c", "b", "user", [{"type": "text", "text": "run ls"}]),
            message(
                "d",
                "c",
                "assistant",
                [
                    {"type": "thinking", "thinking": "planning"},
                    {"type": "text", "text": "Listing files."},
                    {
                        "type": "toolCall",
                        "id": "call-1",
                        "name": "bash",
                        "arguments": {"command": "ls"},
                    },
                ],
                model="claude",
                stopReason="toolUse",
                usage={"cost": {"total": 0.5}},
            ),
            message(
                "e",
                "d",
                "toolResult",
                [
                    {"type": "text", "text": "a.txt"},
                    {"type": "image", "mimeType": "image/png", "data": "aGk="},
                ],
                toolName="bash",
                isError=False,
            ),
            {
                "type": "compaction",
                "id": "f",
                "parentId": "e",
                "timestamp": "t3",
                "summary": "## Goal",
                "tokensBefore": 4000,
            },
            {
                "type": "custom",
                "customType": "plannotator",
                "data": {"phase": "idle"},
                "id": "g",
                "parentId": "f",
                "timestamp": "t4",
            },
            {"type": "mystery", "id": "h", "parentId": "g", "payload": [1, 2]},
        ],
    )

    parsed = pi.parse(session)

    assert parsed["agent"] == "pi"
    assert parsed["meta"] == {
        "session_id": "sess-1",
        "started": "2026-08-20T10:00:00.000Z",
        "cwd": "/home/user/project",
        "version": 3,
    }
    kinds = [record["kind"] for record in parsed["records"]]
    assert kinds == [
        "model_change",
        "thinking_level",
        "user",
        "assistant",
        "tool_result",
        "compaction",
        "custom",
        "unknown",
    ]
    assert [record["parentId"] for record in parsed["records"]] == [
        None,
        "a",
        "b",
        "c",
        "d",
        "e",
        "f",
        "g",
    ]

    user, assistant, result = parsed["records"][2:5]
    assert user["parts"] == [{"type": "text", "text": "run ls"}]
    assert assistant["model"] == "claude"
    assert assistant["usage"] == {"cost": {"total": 0.5}}
    assert assistant["parts"] == [
        {"type": "thinking", "text": "planning"},
        {"type": "text", "text": "Listing files."},
        {"type": "tool_call", "name": "bash", "arguments": {"command": "ls"}},
    ]
    assert result["toolName"] == "bash"
    assert result["isError"] is False
    assert result["parts"] == [
        {"type": "text", "text": "a.txt"},
        {"type": "image", "mimeType": "image/png", "data": "aGk="},
    ]

    unknown = parsed["records"][7]
    assert unknown["raw"] == {
        "type": "mystery",
        "id": "h",
        "parentId": "g",
        "payload": [1, 2],
    }


def test_parse_keeps_branches_and_falls_back_to_raw_lines(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    write_session(
        session,
        [
            message("a", None, "user", [{"type": "text", "text": "first"}]),
            message("b", "a", "user", [{"type": "text", "text": "branch one"}]),
            message("c", "a", "user", [{"type": "text", "text": "branch two"}]),
            "this line is not json",
            message("d", "c", "unknown-role", [{"type": "strange"}]),
        ],
    )

    parsed = pi.parse(session)
    records = parsed["records"]

    assert [record["parentId"] for record in records[:3]] == [None, "a", "a"]
    raw_line = records[3]
    assert raw_line["kind"] == "unknown"
    assert raw_line["raw"] == "this line is not json"
    assert raw_line["parentId"] == "c"
    assert records[4]["kind"] == "unknown"
    assert records[4]["raw"]["message"]["role"] == "unknown-role"
