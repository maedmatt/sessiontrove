import os
import sqlite3
from pathlib import Path

import pytest

from sessiontrove.archive import Source, archive, default_sources


def test_default_sources_use_standard_locations(tmp_path: Path) -> None:
    sources = default_sources(tmp_path, {})

    assert {source.agent for source in sources} == {
        "claude-code",
        "codex",
        "opencode",
        "pi",
    }
    assert any(source.path == tmp_path / ".codex/sessions" for source in sources)
    assert any(
        source.path == tmp_path / ".codex/archived_sessions" for source in sources
    )
    assert any(source.path == tmp_path / ".pi/agent/sessions" for source in sources)


def test_environment_overrides_data_and_claude_locations(tmp_path: Path) -> None:
    sources = default_sources(
        tmp_path,
        {"XDG_DATA_HOME": "/data", "CLAUDE_CONFIG_DIR": "/claude"},
    )

    assert any(source.path == Path("/data/opencode/opencode.db") for source in sources)
    assert any(source.path == Path("/claude/projects") for source in sources)


def test_archive_is_filtered_private_incremental_and_non_destructive(
    tmp_path: Path,
) -> None:
    root = tmp_path / "sessions"
    nested = root / "project"
    nested.mkdir(parents=True)
    session = nested / "session.jsonl"
    session.write_text("conversation", encoding="utf-8")
    (nested / "notes.txt").write_text("ignore", encoding="utf-8")
    (nested / "linked.jsonl").symlink_to(session)
    destination = tmp_path / "archive"
    source = Source("agent", root, Path("sessions"), ("*.jsonl",))

    assert archive(destination, (source,)) == {"agent": 1}
    assert archive(destination, (source,)) == {"agent": 0}

    copied = destination / "agent/sessions/project/session.jsonl"
    assert copied.read_text(encoding="utf-8") == "conversation"
    assert not (destination / "agent/sessions/project/notes.txt").exists()
    assert not (destination / "agent/sessions/project/linked.jsonl").exists()
    assert os.stat(destination).st_mode & 0o777 == 0o700
    assert os.stat(copied).st_mode & 0o777 == 0o600

    session.unlink()
    assert archive(destination, (source,)) == {"agent": 0}
    assert copied.exists()


def test_live_sqlite_database_gets_a_consistent_snapshot(tmp_path: Path) -> None:
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

    assert archive(destination, (source,)) == {"agent": 1}
    assert archive(destination, (source,)) == {"agent": 0}
    with sqlite3.connect(destination / "agent/sessions.db") as snapshot:
        assert snapshot.execute("SELECT text FROM messages").fetchall() == [("hello",)]

    connection.execute("INSERT INTO messages VALUES ('again')")
    connection.commit()
    assert archive(destination, (source,)) == {"agent": 1}
    with sqlite3.connect(destination / "agent/sessions.db") as snapshot:
        assert snapshot.execute("SELECT count(*) FROM messages").fetchone() == (2,)
    connection.close()


def test_destination_cannot_be_inside_a_source(tmp_path: Path) -> None:
    source = Source("agent", tmp_path, Path("sessions"), ("*.jsonl",))

    with pytest.raises(ValueError, match="destination cannot be inside"):
        archive(tmp_path / "archive", (source,))
