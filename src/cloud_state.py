"""GitHub Actions durable state via a release asset, not expiring workflow artifacts."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

TAG = "paper-state"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, stdout=subprocess.PIPE, text=True).stdout


def restore() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    path = Path(os.environ.get("PAPER_DB", "data/paper.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("Refusing to overwrite local state")
    # Listing succeeds independently of whether the state release exists. Auth/network errors fail.
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    release = next((r for page in pages for r in page if r["tag_name"] == TAG), None)
    if release is None:
        if os.getenv("INITIALIZE", "false").lower() != "true":
            raise ValueError("No state release. First run must be manual with initialize=true")
        print("Explicitly initializing a new $100,000 paper account")
        return
    gh(
        "release",
        "download",
        TAG,
        "--repo",
        repo,
        "--pattern",
        "paper.db",
        "--dir",
        str(path.parent),
    )
    downloaded = path.parent / "paper.db"
    if downloaded != path:
        downloaded.rename(path)
    with sqlite3.connect(path) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("State database integrity check failed")
        if db.execute("SELECT COUNT(*) FROM account").fetchone()[0] != 1:
            raise ValueError("State database does not contain an account")


def save() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    path = Path(os.environ.get("PAPER_DB", "data/paper.db"))
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    if not any(r["tag_name"] == TAG for page in pages for r in page):
        if os.getenv("INITIALIZE", "false").lower() != "true":
            raise ValueError("State release disappeared; refusing to recreate it")
        gh(
            "release",
            "create",
            TAG,
            "--repo",
            repo,
            "--title",
            "Persistent paper account",
            "--notes",
            "Paper-only SQLite account. Do not delete or replace with a fresh account.",
            "--latest=false",
        )
    # Keep a previous checkpoint before replacing current state.
    backup = path.parent / "previous"
    backup.mkdir(exist_ok=True)
    release = json.loads(gh("release", "view", TAG, "--repo", repo, "--json", "assets"))
    if any(a["name"] == "paper.db" for a in release["assets"]):
        gh(
            "release",
            "download",
            TAG,
            "--repo",
            repo,
            "--pattern",
            "paper.db",
            "--dir",
            str(backup),
            "--clobber",
        )
        old = backup / "paper.db"
        previous = backup / "paper-previous.db"
        old.replace(previous)
        gh("release", "upload", TAG, str(previous), "--repo", repo, "--clobber")
    gh("release", "upload", TAG, f"{path}#paper.db", "--repo", repo, "--clobber")


if __name__ == "__main__":
    if sys.argv[1:] == ["restore"]:
        restore()
    elif sys.argv[1:] == ["save"]:
        save()
    else:
        raise SystemExit("Usage: python -m src.cloud_state restore|save")
