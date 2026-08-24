import json
from pathlib import Path

from sessiontrove import codex

META = {
    "timestamp": "2026-08-20T10:00:00.000Z",
    "type": "session_meta",
    "payload": {
        "id": "sess-1",
        "timestamp": "2026-08-20T10:00:00.000Z",
        "cwd": "/home/user/project",
    },
}


def envelope(kind: str, payload: dict) -> dict:
    return {"timestamp": "2026-08-20T10:01:00.000Z", "type": kind, "payload": payload}


def write(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        line if isinstance(line, str) else json.dumps(line) for line in lines
    )
    path.write_text(text + "\n", encoding="utf-8")


def test_find_discovers_rollouts_in_both_stores(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    write(
        root / "mac/codex/sessions/2026/08/24/rollout.jsonl",
        [
            META,
            envelope(
                "event_msg",
                {"type": "user_message", "message": " explain  this  repo "},
            ),
        ],
    )
    write(root / "mac/codex/archived_sessions/old.jsonl", [META])
    subagent = dict(META, payload=dict(META["payload"], source={"subagent": "review"}))
    write(root / "mac/codex/sessions/2026/08/24/subagent.jsonl", [subagent])
    guardian = dict(
        META, payload=dict(META["payload"], source={"subagent": {"other": "guardian"}})
    )
    write(root / "mac/codex/sessions/2026/08/24/guardian.jsonl", [guardian])
    write(root / "mac/codex/history.jsonl", [{"text": "prompt"}])
    write(
        root / "mac/codex/session_index.jsonl",
        [{"id": "sess-1", "thread_name": "Explain the repo", "updated_at": "x"}],
    )
    outside = tmp_path / "outside.jsonl"
    write(outside, [META])
    (root / "mac/codex/sessions/link.jsonl").symlink_to(outside)

    found = codex.find(root)

    assert [summary["id"] for summary, _ in found] == [
        "mac/codex/sessions/2026/08/24/rollout.jsonl",
        "mac/codex/archived_sessions/old.jsonl",
    ]
    summary = found[0][0]
    assert summary["agent"] == "codex"
    assert summary["machine"] == "mac"
    assert summary["cwd"] == "/home/user/project"
    assert summary["preview"] == "explain this repo"
    assert summary["title"] == "Explain the repo"


def test_parse_maps_and_deduplicates_the_two_streams(tmp_path: Path) -> None:
    session = tmp_path / "rollout.jsonl"
    write(
        session,
        [
            META,
            envelope(
                "turn_context",
                {"model": "gpt-5-codex", "effort": "medium", "cwd": "/x"},
            ),
            envelope("event_msg", {"type": "user_message", "message": "run ls"}),
            envelope(
                "response_item",
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "<environment>"}],
                },
            ),
            envelope(
                "response_item",
                {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "planning"}],
                    "encrypted_content": "xxx",
                },
            ),
            envelope("event_msg", {"type": "agent_reasoning", "text": "planning"}),
            envelope(
                "response_item",
                {
                    "type": "function_call",
                    "name": "shell",
                    "arguments": '{"command":["bash","-lc","ls"]}',
                    "call_id": "call-1",
                },
            ),
            envelope(
                "response_item",
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": '{"output":"a.txt","metadata":{"exit_code":1}}',
                },
            ),
            envelope("event_msg", {"type": "token_count", "info": None}),
            envelope("event_msg", {"type": "agent_message", "message": "Done."}),
            envelope(
                "turn_context",
                {"model": "gpt-5-codex", "effort": "medium", "cwd": "/x"},
            ),
            envelope("turn_context", {"model": "gpt-5.2-codex", "effort": "medium"}),
            envelope("compacted", {"message": "summary of dropped turns"}),
            envelope("event_msg", {"type": "turn_aborted", "reason": "interrupted"}),
            "broken line",
        ],
    )

    parsed = codex.parse(session)

    assert parsed["meta"] == {
        "session_id": "sess-1",
        "started": "2026-08-20T10:00:00.000Z",
        "cwd": "/home/user/project",
    }
    kinds = [record["kind"] for record in parsed["records"]]
    assert kinds == [
        "model_change",
        "thinking_level",
        "user",
        "assistant",
        "assistant",
        "tool_result",
        "assistant",
        "model_change",
        "compaction",
        "custom",
        "unknown",
    ]

    chain = [record["parentId"] for record in parsed["records"]]
    assert chain == [None] + [record["id"] for record in parsed["records"][:-1]]

    reasoning, call = parsed["records"][3], parsed["records"][4]
    assert reasoning["parts"] == [{"type": "thinking", "text": "planning"}]
    assert call["model"] == "gpt-5-codex"
    assert call["parts"][0]["name"] == "shell"

    result = parsed["records"][5]
    assert result["toolName"] == "shell"
    assert result["isError"] is True
    assert result["parts"] == [{"type": "text", "text": "a.txt"}]

    answer = parsed["records"][6]
    assert answer["parts"] == [{"type": "text", "text": "Done."}]
    assert parsed["records"][7]["model"] == "gpt-5.2-codex"
    assert parsed["records"][8]["summary"] == "summary of dropped turns"
    assert parsed["records"][9]["customType"] == "turn_aborted"
    assert parsed["records"][10]["raw"] == "broken line"


def test_parse_handles_newer_multi_agent_rollouts(tmp_path: Path) -> None:
    session = tmp_path / "rollout.jsonl"
    write(
        session,
        [
            META,
            envelope("world_state", {"full": True, "state": {}}),
            envelope("inter_agent_communication_metadata", {"x": 1}),
            envelope("event_msg", {"type": "thread_settings_applied", "settings": {}}),
            envelope("event_msg", {"type": "sub_agent_activity", "detail": "…"}),
            envelope(
                "response_item",
                {
                    "type": "agent_message",
                    "author": "/root/a",
                    "recipient": "/root/b",
                    "content": [{"type": "input_text", "text": "NEW_TASK"}],
                },
            ),
            envelope(
                "response_item",
                {
                    "type": "tool_search_call",
                    "call_id": "call-2",
                    "arguments": '{"query": "read file"}',
                },
            ),
            envelope(
                "response_item",
                {
                    "type": "tool_search_output",
                    "call_id": "call-2",
                    "tools": [{"name": "mcp__x"}],
                },
            ),
        ],
    )

    parsed = codex.parse(session)

    kinds = [record["kind"] for record in parsed["records"]]
    assert kinds == ["custom", "assistant", "tool_result"]
    assert parsed["records"][0]["customType"] == "inter-agent message"
    assert parsed["records"][1]["parts"][0]["name"] == "tool_search"
    assert parsed["records"][2]["toolName"] == "tool_search"
