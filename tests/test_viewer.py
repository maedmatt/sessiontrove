import json
import threading
from http.client import HTTPConnection
from pathlib import Path

import pytest

from sessiontrove.viewer import ViewerServer

SESSION_LINES = [
    {
        "type": "session",
        "version": 3,
        "id": "sess-1",
        "timestamp": "2026-08-20T10:00:00.000Z",
        "cwd": "/home/user/project",
    },
    {
        "type": "message",
        "id": "a",
        "parentId": None,
        "timestamp": "2026-08-20T10:01:00.000Z",
        "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
    },
]


CLAUDE_LINES = [
    {
        "type": "user",
        "uuid": "u1",
        "parentUuid": None,
        "sessionId": "sess-2",
        "timestamp": "2026-08-21T10:00:00.000Z",
        "cwd": "/home/user/project",
        "message": {"role": "user", "content": "hello claude"},
    },
]


@pytest.fixture
def archive_root(tmp_path: Path) -> Path:
    root = tmp_path / "archive"
    session = root / "mac/pi/sessions/project/a.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        "".join(json.dumps(line) + "\n" for line in SESSION_LINES), encoding="utf-8"
    )
    claude = root / "mac/claude-code/projects/proj/b.jsonl"
    claude.parent.mkdir(parents=True)
    claude.write_text(
        "".join(json.dumps(line) + "\n" for line in CLAUDE_LINES), encoding="utf-8"
    )
    secret = tmp_path / "secret.jsonl"
    secret.write_text(
        "".join(json.dumps(line) + "\n" for line in SESSION_LINES), encoding="utf-8"
    )
    (root / "mac/pi/sessions/link.jsonl").symlink_to(secret)
    return root


@pytest.fixture
def server(archive_root: Path):
    server = ViewerServer(archive_root)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join()


def get(server: ViewerServer, path: str):
    connection = HTTPConnection("127.0.0.1", server.server_address[1])
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def test_binds_to_localhost_and_serves_locked_down_pages(server: ViewerServer) -> None:
    assert server.server_address[0] == "127.0.0.1"
    status, headers, body = get(server, "/")
    assert status == 200
    assert b"Sessiontrove" in body
    assert headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert headers["X-Content-Type-Options"] == "nosniff"

    status, headers, _ = get(server, "/static/viewer.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")


def test_lists_and_parses_sessions_from_every_reader(server: ViewerServer) -> None:
    status, _, body = get(server, "/api/sessions")
    assert status == 200
    sessions = json.loads(body)
    assert [(s["agent"], s["id"]) for s in sessions] == [
        ("claude-code", "mac/claude-code/projects/proj/b.jsonl"),
        ("pi", "mac/pi/sessions/project/a.jsonl"),
    ]
    assert sessions[1]["machine"] == "mac"
    assert sessions[1]["preview"] == "hello"

    status, _, body = get(server, "/api/session?id=mac/pi/sessions/project/a.jsonl")
    assert status == 200
    parsed = json.loads(body)
    assert parsed["agent"] == "pi"
    assert parsed["meta"]["cwd"] == "/home/user/project"
    assert [record["kind"] for record in parsed["records"]] == ["user"]

    status, _, body = get(
        server, "/api/session?id=mac/claude-code/projects/proj/b.jsonl"
    )
    assert status == 200
    assert json.loads(body)["agent"] == "claude-code"


def test_rejects_traversal_symlinks_and_unknown_paths(server: ViewerServer) -> None:
    for path in (
        "/api/session?id=../secret.jsonl",
        "/api/session?id=mac/pi/sessions/../../../secret.jsonl",
        "/api/session?id=/etc/passwd",
        "/api/session?id=mac/pi/sessions/link.jsonl",
        "/api/session",
        "/static/../viewer.py",
        "/static/%2e%2e/secret.jsonl",
        "/secret.jsonl",
    ):
        status, _, body = get(server, path)
        assert status == 404, path
        assert b"secret" not in body, path

    _, _, body = get(server, "/api/sessions")
    assert "link.jsonl" not in body.decode()


def test_viewing_never_modifies_the_archive(
    server: ViewerServer, archive_root: Path
) -> None:
    before = {
        path: path.stat().st_mtime_ns
        for path in archive_root.rglob("*")
        if path.is_file()
    }
    get(server, "/api/sessions")
    get(server, "/api/session?id=mac/pi/sessions/project/a.jsonl")
    after = {
        path: path.stat().st_mtime_ns
        for path in archive_root.rglob("*")
        if path.is_file()
    }
    assert after == before
