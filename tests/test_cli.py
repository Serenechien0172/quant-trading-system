import sys

from conftest import seed

from src.main import main
from src.storage import connect


def test_cli_pipeline_and_reports(tmp_path, monkeypatch, capsys):
    path = tmp_path / "paper.db"
    monkeypatch.setenv("PAPER_DB", str(path))
    db = connect(path)
    seed(db, "2026-01-02")
    db.close()
    monkeypatch.setattr("src.main.latest_completed", lambda: "2026-01-02")
    for args in (
        ["pipeline", "--strategy", "dummy"],
        ["portfolio"],
        ["trades"],
        ["performance"],
        ["history"],
    ):
        monkeypatch.setattr(sys, "argv", ["paper", *args])
        assert main() == 0
    output = capsys.readouterr().out
    assert "99,999.00" in output
    assert "BUY" in output
    assert "N/A" in output


def test_cli_missing_data_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_DB", str(tmp_path / "empty.db"))
    monkeypatch.setattr(sys, "argv", ["paper", "pipeline"])
    assert main() == 1
