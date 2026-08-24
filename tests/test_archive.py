import os
import sqlite3
from pathlib import Path

import pytest

from sessiontrove.archive import Source, archive, default_sources

MACHINE = "macbookpro-m4"


def write(path: Path, content: str = "data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_source_registry_covers_each_persistent_conversation_store(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    data = tmp_path / "data"
    claude = tmp_path / "claude"

    assert default_sources(
        home,
        {"XDG_DATA_HOME": str(data), "CLAUDE_CONFIG_DIR": str(claude)},
    ) == (
        Source(
            "claude-code",
            claude / "projects",
            Path("projects"),
            ("*.jsonl", "agent-*.meta.json"),
        ),
        Source(
            "claude-code",
            claude / "history.jsonl",
            Path("history.jsonl"),
            ("*.jsonl",),
        ),
        Source(
            "codex",
            home / ".codex/sessions",
            Path("sessions"),
            ("*.jsonl",),
        ),
        Source(
            "codex",
            home / ".codex/archived_sessions",
            Path("archived_sessions"),
            ("*.jsonl",),
        ),
        Source(
            "codex",
            home / ".codex/history.jsonl",
            Path("history.jsonl"),
            ("*.jsonl",),
        ),
        Source(
            "opencode",
            data / "opencode/storage",
            Path("storage"),
            ("*.json",),
        ),
        Source(
            "opencode",
            data / "opencode/opencode.db",
            Path("opencode.db"),
            ("*.db",),
            sqlite=True,
        ),
        Source(
            "pi",
            home / ".pi/agent/sessions",
            Path("sessions"),
            ("*.jsonl",),
        ),
    )


def test_archives_complete_provider_layouts_without_unrelated_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    data = tmp_path / "data"
    claude = home / ".claude"

    write(claude / "history.jsonl", '{"display":"old prompt"}\n')
    write(claude / "projects/project/session.jsonl")
    write(claude / "projects/project/session/subagents/agent-one.jsonl")
    write(claude / "projects/project/session/subagents/agent-one.meta.json")
    write(claude / "projects/project/sessions-index.json", "not a conversation")
    write(claude / "settings.json", "not a conversation")

    write(home / ".codex/sessions/2026/08/24/rollout.jsonl")
    write(home / ".codex/archived_sessions/archived.jsonl")
    write(home / ".codex/history.jsonl", '{"text":"old prompt"}\n')
    write(home / ".codex/session_index.jsonl", "not a conversation")
    write(home / ".codex/auth.json", "secret")

    write(data / "opencode/storage/message/session/message.json", "{}")
    write(data / "opencode/storage/part/message/part.json", "{}")
    database = data / "opencode/opencode.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE message (text TEXT)")
        connection.execute("INSERT INTO message VALUES ('conversation')")
    write(data / "opencode/auth.json", "secret")

    write(home / ".pi/agent/sessions/project/session.jsonl")
    write(home / ".pi/agent/settings.json", "not a conversation")

    destination = tmp_path / "archive"
    results = archive(
        destination,
        MACHINE,
        default_sources(home, {"XDG_DATA_HOME": str(data)}),
    )

    assert results == {
        "claude-code": 4,
        "codex": 3,
        "opencode": 3,
        "pi": 1,
    }
    archived = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert archived == {
        "macbookpro-m4/claude-code/history.jsonl",
        "macbookpro-m4/claude-code/projects/project/session.jsonl",
        "macbookpro-m4/claude-code/projects/project/session/subagents/agent-one.jsonl",
        "macbookpro-m4/claude-code/projects/project/session/subagents/agent-one.meta.json",
        "macbookpro-m4/codex/archived_sessions/archived.jsonl",
        "macbookpro-m4/codex/history.jsonl",
        "macbookpro-m4/codex/sessions/2026/08/24/rollout.jsonl",
        "macbookpro-m4/opencode/opencode.db",
        "macbookpro-m4/opencode/storage/message/session/message.json",
        "macbookpro-m4/opencode/storage/part/message/part.json",
        "macbookpro-m4/pi/sessions/project/session.jsonl",
    }
    with sqlite3.connect(
        destination / "macbookpro-m4/opencode/opencode.db"
    ) as snapshot:
        assert snapshot.execute("SELECT text FROM message").fetchone() == (
            "conversation",
        )


def test_machine_directories_keep_shared_archives_separate(tmp_path: Path) -> None:
    session = tmp_path / "source/session.jsonl"
    write(session, "from mac")
    source = Source("pi", session.parent, Path("sessions"), ("*.jsonl",))
    destination = tmp_path / "archive"

    assert archive(destination, "macbookpro-m4", (source,)) == {"pi": 1}
    session.write_text("from linux", encoding="utf-8")
    assert archive(destination, "linux-workstation", (source,)) == {"pi": 1}

    mac = destination / "macbookpro-m4/pi/sessions/session.jsonl"
    linux = destination / "linux-workstation/pi/sessions/session.jsonl"
    assert mac.read_text() == "from mac"
    assert linux.read_text() == "from linux"


def test_reruns_update_changed_sessions_but_keep_deleted_sessions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    session = root / "project/session.jsonl"
    ignored = root / "project/notes.txt"
    linked = root / "project/linked.jsonl"
    write(session, "first")
    write(ignored, "ignore")
    linked.symlink_to(session)
    source = Source("agent", root, Path("sessions"), ("*.jsonl",))
    destination = tmp_path / "archive"

    assert archive(destination, MACHINE, (source,)) == {"agent": 1}
    assert archive(destination, MACHINE, (source,)) == {"agent": 0}

    copied = destination / "macbookpro-m4/agent/sessions/project/session.jsonl"
    assert copied.read_text(encoding="utf-8") == "first"
    assert not (destination / "macbookpro-m4/agent/sessions/project/notes.txt").exists()
    assert not (
        destination / "macbookpro-m4/agent/sessions/project/linked.jsonl"
    ).exists()
    assert os.stat(destination).st_mode & 0o777 == 0o700
    assert os.stat(destination / MACHINE).st_mode & 0o777 == 0o700
    assert os.stat(copied).st_mode & 0o777 == 0o600

    session.write_text("second version", encoding="utf-8")
    assert archive(destination, MACHINE, (source,)) == {"agent": 1}
    assert copied.read_text(encoding="utf-8") == "second version"

    session.unlink()
    assert archive(destination, MACHINE, (source,)) == {"agent": 0}
    assert copied.read_text(encoding="utf-8") == "second version"


def test_live_sqlite_wal_is_included_in_the_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "sessions.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE messages (text TEXT)")
    connection.execute("INSERT INTO messages VALUES ('hello')")
    connection.commit()
    source = Source(
        "agent",
        database,
        Path("sessions.db"),
        ("*.db",),
        sqlite=True,
    )
    destination = tmp_path / "archive"

    assert archive(destination, MACHINE, (source,)) == {"agent": 1}
    assert archive(destination, MACHINE, (source,)) == {"agent": 0}
    snapshot_path = destination / "macbookpro-m4/agent/sessions.db"
    with sqlite3.connect(snapshot_path) as snapshot:
        assert snapshot.execute("SELECT text FROM messages").fetchall() == [("hello",)]

    connection.execute("INSERT INTO messages VALUES ('again')")
    connection.commit()
    assert archive(destination, MACHINE, (source,)) == {"agent": 1}
    with sqlite3.connect(snapshot_path) as snapshot:
        assert snapshot.execute("SELECT count(*) FROM messages").fetchone() == (2,)
    connection.close()


def test_destination_cannot_be_inside_a_source(tmp_path: Path) -> None:
    source = Source("agent", tmp_path, Path("sessions"), ("*.jsonl",))

    with pytest.raises(ValueError, match="destination cannot be inside"):
        archive(tmp_path / "archive", MACHINE, (source,))


@pytest.mark.parametrize("machine", ["", "../other", "mac/book", "mac book"])
def test_machine_is_a_single_safe_directory_name(tmp_path: Path, machine: str) -> None:
    with pytest.raises(ValueError, match="machine must contain only"):
        archive(tmp_path / "archive", machine, ())
