import json
import subprocess

import pytest

from src import cloud_state


@pytest.fixture
def cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/quant-trading-system")
    monkeypatch.setenv("PAPER_DB", str(tmp_path / "paper.db"))
    monkeypatch.delenv("INITIALIZE", raising=False)
    return tmp_path


def test_missing_cloud_state_never_silently_initializes(cloud, monkeypatch):
    monkeypatch.setattr(cloud_state, "gh", lambda *args: "[[]]")
    with pytest.raises(ValueError, match="First run"):
        cloud_state.restore()
    monkeypatch.setenv("INITIALIZE", "true")
    cloud_state.restore()
    assert not (cloud / "paper.db").exists()


def test_auth_error_does_not_initialize(cloud, monkeypatch):
    monkeypatch.setenv("INITIALIZE", "true")

    def fail(*args):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(cloud_state, "gh", fail)
    with pytest.raises(subprocess.CalledProcessError):
        cloud_state.restore()


def test_existing_release_missing_asset_is_fatal(cloud, monkeypatch):
    monkeypatch.setenv("INITIALIZE", "true")

    def fake(*args):
        if args[0] == "api":
            return json.dumps([[{"tag_name": "paper-state"}]])
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(cloud_state, "gh", fake)
    with pytest.raises(subprocess.CalledProcessError):
        cloud_state.restore()


def test_save_refuses_disappeared_release(cloud, monkeypatch):
    monkeypatch.setattr(cloud_state, "gh", lambda *args: "[[]]")
    with pytest.raises(ValueError, match="disappeared"):
        cloud_state.save()


def test_restore_refuses_local_overwrite(cloud):
    (cloud / "paper.db").touch()
    with pytest.raises(ValueError, match="overwrite"):
        cloud_state.restore()
