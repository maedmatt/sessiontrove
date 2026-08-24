from pathlib import Path

from sessiontrove.archive import Source
from sessiontrove.cli import main


def test_archive_command_archives_sessions_and_reports_updates(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    session = tmp_path / "source/session.jsonl"
    session.parent.mkdir()
    session.write_text("conversation", encoding="utf-8")
    source = Source("pi", session.parent, Path("sessions"), ("*.jsonl",))
    monkeypatch.setattr(
        "sessiontrove.archive.default_sources",
        lambda: (source,),
    )
    destination = tmp_path / "archive"

    assert main(["archive", str(destination), "--machine", "macbookpro-m4"]) == 0
    assert capsys.readouterr().out == "pi: 1 files updated\n"
    archived = destination / "macbookpro-m4/pi/sessions/session.jsonl"
    assert archived.read_text() == "conversation"


def test_view_command_serves_the_archive(tmp_path: Path, monkeypatch) -> None:
    calls = {}

    def fake_serve(root: Path, port: int, open_browser: bool) -> int:
        calls["args"] = (root, port, open_browser)
        return 0

    monkeypatch.setattr("sessiontrove.cli.serve", fake_serve)

    assert main(["view", str(tmp_path), "--port", "8123", "--no-browser"]) == 0
    assert calls["args"] == (tmp_path, 8123, False)


def test_view_command_requires_an_existing_directory(tmp_path: Path, capsys) -> None:
    assert main(["view", str(tmp_path / "missing")]) == 1
    assert "not a directory" in capsys.readouterr().err
