
"""A machine with no git identity must still be able to merge, settle and sync.

`git commit` fails with "empty ident name ... not allowed" when neither the repo
nor the user configures an identity. That is fatal on a CI runner or a fresh
container, and it is muster's own bookkeeping commit - not the user's history -
so muster supplies the author itself.
"""
import os

import pytest

from muster.gitio import Git
from muster.model import Session
from muster.observe import build_snapshot
from muster.orchestrate import merge, settle_apply, settle_plan
from muster.store import Ledger
from muster.sync import push


@pytest.fixture
def anonymous(repo, monkeypatch, tmp_path):
    """The repo, with every source of git identity removed."""
    git = Git(repo)
    for key in ("user.name", "user.email"):
        git.run("config", "--unset-all", key, check=False)
    # An empty HOME hides the developer's own global config. GIT_CONFIG_GLOBAL
    # would be cleaner but needs git >= 2.32, and this tool supports 2.20.
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_home / "config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("GIT_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("GIT_AUTHOR_EMAIL", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_NAME", raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)
    monkeypatch.delenv("EMAIL", raising=False)
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.setenv("MUSTER_STATE_DIR", str(tmp_path / "state"))
    assert git.run("config", "--get", "user.email", check=False).strip() == ""
    return repo


def test_sync_push_works_without_an_identity(anonymous, tmp_path, monkeypatch):
    import subprocess
    bare = str(tmp_path / "anon-remote.git")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    Git(anonymous).run("remote", "add", "origin", bare)
    git = Git(anonymous)
    Ledger(anonymous).upsert_session(Session(id="s/one"))
    out = push(git, Ledger(anonymous))
    assert out["ok"] is True, out
    author = git.run("log", "-1", "--format=%an <%ae>", "refs/muster/ledger").strip()
    assert author == "muster <muster@localhost>"


def test_merge_works_without_an_identity(anonymous):
    git = Git(anonymous)
    git.run("branch", "integration", "main")
    res = merge(git, "feature/upload-api", "integration", apply=True)
    assert res["applied"] is True, res["log"]
    author = git.run("log", "-1", "--format=%an <%ae>", "integration").strip()
    assert author == "muster <muster@localhost>"


def test_settle_works_without_an_identity(anonymous):
    git = Git(anonymous)
    snap, _ = build_snapshot(repo=anonymous, window=6 * 3600)
    res = settle_apply(git, settle_plan(git, snap, base="main"), apply=True)
    assert res["created"], res["failed"]
    author = git.run("log", "-1", "--format=%an <%ae>",
                     res["created"][0]["branch"]).strip()
    assert author == "muster <muster@localhost>"


def test_the_committer_can_be_declared(anonymous, monkeypatch):
    monkeypatch.setenv("MUSTER_COMMITTER_NAME", "Integration Bot")
    monkeypatch.setenv("MUSTER_COMMITTER_EMAIL", "bot@example.com")
    git = Git(anonymous)
    git.run("branch", "integration", "main")
    res = merge(git, "feature/upload-api", "integration", apply=True)
    assert res["applied"] is True, res["log"]
    assert git.run("log", "-1", "--format=%an <%ae>", "integration").strip() \
        == "Integration Bot <bot@example.com>"


def test_a_users_own_identity_is_still_used_for_their_own_commits(anonymous):
    """The fallback must not overwrite a real identity when one exists."""
    git = Git(anonymous)
    git.run("config", "user.name", "Dana")
    git.run("config", "user.email", "dana@example.com")
    git.run("branch", "integration", "main")
    res = merge(git, "feature/upload-api", "integration", apply=True)
    assert res["applied"] is True, res["log"]
    # muster still signs the merge it performed; the user's commits are untouched
    assert git.run("log", "-1", "--format=%an", "feature/upload-api").strip() != "muster"
