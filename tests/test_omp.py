import json
from pathlib import Path

from sessiontrove import omp

LINES = [
    {
        "type": "title",
        "v": 1,
        "title": "Identify the AI model",
        "source": "auto",
        "pad": " ",
    },
    {
        "type": "session",
        "version": 3,
        "id": "sess-1",
        "timestamp": "2026-08-20T10:00:00.000Z",
        "cwd": "/home/user/project",
        "title": "Identify the AI model",
        "titleSource": "auto",
    },
    {
        "type": "message",
        "id": "a",
        "parentId": None,
        "timestamp": "2026-08-20T10:01:00.000Z",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "which model are you?"}],
        },
    },
]


def write(path: Path, lines: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )


def test_find_reads_the_omp_store_with_titles(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    write(root / "mac/omp/sessions/project/a.jsonl", LINES)
    attachment = root / "mac/omp/sessions/project/a-dir/notes.md"
    attachment.parent.mkdir(parents=True)
    attachment.write_text("sidecar attachment", encoding="utf-8")

    found = omp.find(root)

    assert [summary["id"] for summary, _ in found] == [
        "mac/omp/sessions/project/a.jsonl"
    ]
    summary = found[0][0]
    assert summary["agent"] == "omp"
    assert summary["machine"] == "mac"
    assert summary["title"] == "Identify the AI model"
    assert summary["preview"] == "which model are you?"


def test_parse_keeps_the_title_and_agent(tmp_path: Path) -> None:
    session = tmp_path / "session.jsonl"
    write(session, LINES)

    parsed = omp.parse(session)

    assert parsed["agent"] == "omp"
    assert parsed["meta"]["title"] == "Identify the AI model"
    assert parsed["meta"]["session_id"] == "sess-1"
    assert [record["kind"] for record in parsed["records"]] == ["user"]
