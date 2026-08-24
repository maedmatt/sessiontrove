import json
from pathlib import Path

from sessiontrove import openclaw


def session_lines(session_id: str, text: str) -> list:
    return [
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": "2026-08-20T10:00:00.000Z",
            "cwd": "/home/kai/.openclaw/workspace",
        },
        {
            "type": "message",
            "id": "a",
            "parentId": None,
            "timestamp": "2026-08-20T10:01:00.000Z",
            "message": {"role": "user", "content": text},
        },
    ]


def write(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )


def test_find_walks_personas_and_labels_sessions(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    main = root / "mac/openclaw/agents/main/sessions"
    write(main / "s1.jsonl", session_lines("s1", "check the weather"))
    write(main / "s2.jsonl", session_lines("s2", "unlabeled chat"))
    (main / "sessions.json").write_text(
        json.dumps(
            {
                "agent:main:cron:x": {"sessionId": "s1", "label": "Cron: umbrella"},
                "agent:main:heartbeat": {"sessionId": "missing"},
            }
        ),
        encoding="utf-8",
    )
    write(
        root / "mac/openclaw/agents/sable/sessions/s3.jsonl",
        session_lines("s3", "hello sable"),
    )
    trajectory = main / "s1.trajectory.jsonl"
    trajectory.write_text(
        '{"traceSchema":"openclaw-trajectory","type":"session.started"}\n',
        encoding="utf-8",
    )

    found = openclaw.find(root)

    rows = [(s["id"], s["title"]) for s, _ in found]
    assert rows == [
        ("mac/openclaw/agents/main/sessions/s1.jsonl", "Cron: umbrella"),
        ("mac/openclaw/agents/main/sessions/s2.jsonl", "main"),
        ("mac/openclaw/agents/sable/sessions/s3.jsonl", "sable"),
    ]
    assert all(s["agent"] == "openclaw" for s, _ in found)
    assert found[0][0]["preview"] == "check the weather"


def test_parse_handles_string_content(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    write(session, session_lines("s1", "plain string content"))

    parsed = openclaw.parse(session)

    assert parsed["agent"] == "openclaw"
    user = parsed["records"][0]
    assert user["kind"] == "user"
    assert user["parts"] == [{"type": "text", "text": "plain string content"}]
