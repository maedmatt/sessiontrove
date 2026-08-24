from pathlib import Path

from sessiontrove.cli import main


def test_main_reports_updates(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sessiontrove.cli.archive",
        lambda destination: {"pi": 2, "codex": 1},
    )

    assert main([str(tmp_path / "archive")]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "codex: 1 files updated",
        "pi: 2 files updated",
    ]


def test_main_reports_when_no_session_store_exists(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("sessiontrove.cli.archive", lambda destination: {})

    assert main([str(tmp_path / "archive")]) == 1
    assert "no supported session stores found" in capsys.readouterr().err


def test_main_reports_archive_errors(tmp_path: Path, monkeypatch, capsys) -> None:
    def fail(destination: Path) -> dict[str, int]:
        raise OSError("copy failed")

    monkeypatch.setattr("sessiontrove.cli.archive", fail)

    assert main([str(tmp_path / "archive")]) == 1
    assert "error: copy failed" in capsys.readouterr().err
