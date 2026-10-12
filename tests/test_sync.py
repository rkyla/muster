
"""The ledger over a git ref: sessions on other machines, no server."""
import json

from muster.gitio import Git
from muster.model import Session
from muster.store import Ledger
from muster.sync import REF, export_doc, pull, push, repo_id, status


def test_repo_id_is_stable_and_shared_by_clones(two_clones):
    a, b, _remote = two_clones
    assert repo_id(Git(a)) == repo_id(Git(b)), "clones are one project"


def test_an_unrelated_repo_gets_its_own_id(tmp_path):
    import os
    import subprocess
    here = str(tmp_path / "here")
    there = str(tmp_path / "there")
    for path in (here, there):
        os.makedirs(path)
        subprocess.run(["git", "init", "-q", path], check=True)
        with open(os.path.join(path, "f.txt"), "w") as fh:
            fh.write(path)
        subprocess.run(["git", "-C", path, "add", "-A"], check=True)
        subprocess.run(["git", "-C", path, "-c", "user.email=a@b", "-c", "user.name=a",
                        "commit", "-q", "-m", "s"], check=True)
    assert repo_id(Git(here)) != repo_id(Git(there))


def test_export_doc_declares_its_schema_and_repo(two_clones):
    a, _b, _remote = two_clones
    led = Ledger(a)
    led.upsert_session(Session(id="claude-code/hero", harness="claude-code",
                               intent="hero redesign"))
    doc = export_doc(Git(a), led)
    assert doc["schema"] == "muster/ledger-export/1"
    assert doc["repo_id"] == repo_id(Git(a))
    assert [s["id"] for s in doc["sessions"]] == ["claude-code/hero"]


def test_push_dry_run_writes_no_ref(two_clones):
    a, _b, _remote = two_clones
    git = Git(a)
    led = Ledger(a)
    led.upsert_session(Session(id="s/one"))
    out = push(git, led, dry_run=True)
    assert out["dry_run"] is True
    assert git.run("rev-parse", "-q", "--verify", REF, check=False).strip() == ""


def test_push_without_a_remote_reports_failure_not_a_traceback(repo):
    git = Git(repo)
    out = push(git, Ledger(repo))
    assert out["ok"] is False
    assert "remote" in out["error"]


def test_a_session_pushed_on_one_clone_is_visible_on_the_other(two_clones):
    a, b, _remote = two_clones
    git_a, git_b = Git(a), Git(b)
    Ledger(a).upsert_session(Session(id="claude-code/hero", harness="claude-code",
                                     intent="hero redesign", paths=["site/"]))
    assert push(git_a, Ledger(a))["ok"] is True

    out = pull(git_b, Ledger(b))
    assert out["ok"] is True, out
    ids = {s.id for s in Ledger(b).sessions()}
    assert "claude-code/hero" in ids
    hero = [s for s in Ledger(b).sessions() if s.id == "claude-code/hero"][0]
    assert hero.intent == "hero redesign"


def test_pull_does_not_invent_sessions_when_the_remote_has_none(two_clones):
    _a, b, _remote = two_clones
    out = pull(Git(b), Ledger(b))
    assert out["ok"] is False
    assert "nothing" in out["error"].lower()


def test_a_foreign_project_is_not_merged_into_your_ledger(two_clones, tmp_path):
    """repo_id is the only thing stopping another project's sessions appearing."""
    import os
    import subprocess
    a, _b, _remote = two_clones
    stranger = str(tmp_path / "stranger")
    subprocess.run(["git", "init", "-q", stranger], check=True)
    with open(os.path.join(stranger, "f.txt"), "w") as fh:
        fh.write("x\n")
    subprocess.run(["git", "-C", stranger, "add", "-A"], check=True)
    subprocess.run(["git", "-C", stranger, "-c", "user.email=a@b", "-c", "user.name=a",
                    "commit", "-q", "-m", "s"], check=True)
    subprocess.run(["git", "-C", stranger, "remote", "add", "origin", Git(a).toplevel()],
                   check=True)
    Ledger(stranger).upsert_session(Session(id="other-project/session"))
    # the stranger publishes under its own id; pulling it into a must be refused
    assert push(Git(stranger), Ledger(stranger))["ok"] is True
    out = pull(Git(a), Ledger(a))
    assert out["ok"] is False
    assert "different repository" in out["error"]
    assert "other-project/session" not in {s.id for s in Ledger(a).sessions()}


def test_status_reports_what_is_published(two_clones):
    a, _b, _remote = two_clones
    git = Git(a)
    led = Ledger(a)
    led.upsert_session(Session(id="s/one"))
    assert status(git, led)["local_commit"] is None
    push(git, led)
    st = status(git, led)
    assert st["local_commit"]
    assert st["ref"] == REF


def test_sync_cli_push_and_pull(two_clones, capsys):
    from muster import cli
    a, b, _remote = two_clones
    Ledger(a).upsert_session(Session(id="cli/one", intent="from the cli"))
    assert cli.main(["sync", "push", "--repo", a]) == 0
    assert "ok" in capsys.readouterr().out.lower()
    assert cli.main(["sync", "pull", "--repo", b]) == 0
    assert "cli/one" in {s.id for s in Ledger(b).sessions()}
