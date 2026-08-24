from pathlib import Path

from sessiontrove.archive import Source
from sessiontrove.cli import main


def test_command_archives_sessions_and_reports_updates(
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

    assert main([str(destination), "--machine", "macbookpro-m4"]) == 0
    assert capsys.readouterr().out == "pi: 1 files updated\n"
    archived = destination / "macbookpro-m4/pi/sessions/session.jsonl"
    assert archived.read_text() == "conversation"
