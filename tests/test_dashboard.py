from pathlib import Path

import pytest
from conftest import seed
from streamlit.testing.v1 import AppTest
from test_demo import HistoricalFixture

from dashboard.data import load_report
from src.config import Settings
from src.demo import simulate
from src.pipeline import run
from src.storage import connect


def test_reports_are_read_only_and_enforce_account_type(tmp_path):
    path = tmp_path / "paper.db"
    db = connect(path)
    seed(db, "2026-01-02")
    run(db, "2026-01-02", Settings(), "dummy")
    db.close()
    before = path.read_bytes()
    report = load_report(path, expect_demo=False)
    assert report.snapshots.iloc[-1].equity == 99999
    assert report.positions.iloc[0]["Shares"] == 1
    assert len(report.trades) == 1
    assert before == path.read_bytes()
    with pytest.raises(ValueError, match="Account type"):
        load_report(path, expect_demo=True)
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        load_report(missing, expect_demo=False)
    assert not missing.exists()


def test_dashboard_demo_metrics_filters_and_live_empty_state(tmp_path, monkeypatch):
    directory = tmp_path / "demos"
    simulate(
        "2025-01-01", "2025-02-03", Settings(), provider=HistoricalFixture(), directory=directory
    )
    monkeypatch.setattr("src.demo.DEMO_DIRECTORY", directory)
    monkeypatch.setenv("PAPER_DB", str(tmp_path / "missing-live.db"))
    app = AppTest.from_file(str(Path("dashboard/app.py").resolve()), default_timeout=30).run()
    assert not app.exception
    assert len(app.metric) == 8
    assert "SPY" in app.markdown[-1].value or any("SPY" in x.value for x in app.markdown)
    app.button_group[1].set_value("3M").run()
    assert not app.exception
    app.button_group[0].set_value("Live paper").run()
    assert not app.exception
    assert app.warning
    assert not (tmp_path / "missing-live.db").exists()
