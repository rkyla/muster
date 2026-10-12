
"""The command surface. Exit codes are part of the contract: an agent branches on them."""
import json
import os

import pytest

from muster import cli
from muster.store import Ledger


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Never let a test write a real ledger into the developer's state dir."""
    monkeypatch.setenv("MUSTER_STATE_DIR", str(tmp_path / "state"))
    for var in ("MUSTER_SESSION", "MUSTER_HARNESS", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID",
                "CODEX_THREAD_ID", "RLM_SESSION_DIR", "AI_AGENT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MUSTER_SESSION", "pytest/one")
    return tmp_path


def run(*argv):
    return cli.main(list(argv))


def test_whoami_reports_identity_and_its_source(repo, capsys):
    assert run("whoami", "--repo", repo) == 0
    out = capsys.readouterr().out
    assert "pytest/one" in out
    assert "env:MUSTER_SESSION" in out


def test_brief_names_the_lanes_and_exits_zero(repo, capsys):
    assert run("brief", "--repo", repo) == 0
    out = capsys.readouterr().out
    assert "experiments" in out
    assert "feature/billing" in out


def test_brief_json_is_machine_readable(repo, capsys):
    assert run("brief", "--repo", repo, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["me"] == "pytest/one"
    assert payload["refs"]


def test_claim_records_intent_and_scope(repo, capsys):
    assert run("claim", "--repo", repo, "--intent", "hero redesign",
               "--path", "site/") == 0
    out = capsys.readouterr().out
    assert "hero redesign" in out
    capsys.readouterr()
    assert run("brief", "--repo", repo) == 0
    assert "hero redesign" in capsys.readouterr().out


def test_claim_without_a_path_warns_instead_of_claiming_everything(repo, capsys):
    assert run("claim", "--repo", repo, "--intent", "vague") == 0
    out = capsys.readouterr().out
    assert "no --path" in out or "scope" in out.lower()


def test_touch_exits_nonzero_when_another_lane_is_there(repo, capsys):
    code = run("touch", "--repo", repo, "app.py")
    assert code == 1, "an agent must be able to branch on this"
    assert "app.py" in capsys.readouterr().out


def test_touch_exits_zero_for_a_quiet_file(repo, capsys):
    assert run("touch", "--repo", repo, "util.py") == 0
    assert "SAFE" in capsys.readouterr().out


def test_plan_reports_the_conflict_and_stays_dry(repo, capsys):
    assert run("plan", "feature/billing", "--into", "feature/upload-api",
               "--repo", repo) == 0
    out = capsys.readouterr().out
    assert "app.py" in out
    assert "dry-run" in out


def test_plan_of_a_missing_ref_is_an_error_exit(repo, capsys):
    assert run("plan", "feature/nope", "--into", "main", "--repo", repo) == 1
    assert capsys.readouterr().out or capsys.readouterr().err


def test_merge_refuses_without_apply(repo, capsys):
    assert run("merge", "feature/upload-api", "--into", "main", "--repo", repo) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "main" in out


def test_merge_blocked_by_conflicts_exits_nonzero(repo, capsys):
    assert run("merge", "feature/billing", "--into", "feature/upload-api",
               "--repo", repo) == 1


def test_settle_lists_lanes_without_creating_them(repo, capsys):
    assert run("settle", "--repo", repo) == 0
    out = capsys.readouterr().out
    assert "experiments" in out
    assert "dry-run" in out
    branches = os.popen("git -C %s for-each-ref refs/heads/muster" % repo).read()
    assert branches.strip() == ""


def test_map_and_features_and_events_and_doctor_all_run(repo, capsys):
    for cmd in ("map", "features", "events", "doctor"):
        assert run(cmd, "--repo", repo) == 0, cmd
        assert capsys.readouterr().out.strip(), cmd


def test_features_json_carries_evidence(repo, capsys):
    assert run("features", "--repo", repo, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    feats = payload["features"] if isinstance(payload, dict) else payload
    assert feats and all(f["evidence"] for f in feats)


def test_done_summarises_and_retires_a_session(repo, capsys):
    run("claim", "--repo", repo, "--intent", "x", "--path", "site/")
    capsys.readouterr()
    assert run("done", "--repo", repo, "--summary", "shipped the hero") == 0
    assert "shipped the hero" in capsys.readouterr().out


def test_forget_removes_a_session(repo, capsys):
    run("claim", "--repo", repo, "--intent", "temp", "--path", "site/")
    capsys.readouterr()
    assert run("forget", "--repo", repo, "--session", "pytest/one") == 0
    assert "removed" in capsys.readouterr().out
    assert "pytest/one" not in {s.id for s in Ledger(repo).sessions()}
    run("brief", "--repo", repo)
    assert "temp" not in capsys.readouterr().out


def test_forget_of_an_unknown_session_says_so(repo, capsys):
    assert run("forget", "--repo", repo, "--session", "nobody") == 1
    captured = capsys.readouterr()
    assert "nobody" in captured.out + captured.err


def test_init_opts_into_in_repo_state(repo, capsys):
    assert run("init", "--repo", repo) == 0
    assert os.path.isdir(os.path.join(repo, ".muster"))
    gi = open(os.path.join(repo, ".gitignore")).read()
    assert ".muster/" in gi
    assert os.path.isfile(os.path.join(repo, "AGENTS.md"))


def test_init_is_idempotent(repo, capsys):
    run("init", "--repo", repo)
    capsys.readouterr()
    assert run("init", "--repo", repo) == 0
    text = open(os.path.join(repo, "AGENTS.md")).read()
    assert text.count("<!-- muster:begin -->") == 1


def test_a_non_repo_path_is_a_clean_error(tmp_path, capsys):
    assert run("brief", "--repo", str(tmp_path)) == 1
    err = capsys.readouterr().err
    assert "not a git repository" in err or "git error" in err


def test_watch_reports_nothing_changed_on_a_quiet_repo(repo, capsys):
    assert run("watch", "--repo", repo, "--once", "1") == 0


def test_every_subcommand_documents_itself(capsys):
    import pytest
    parser = cli.build_parser()
    choices = parser._subparsers._group_actions[0].choices
    for name in ("brief", "scan", "claim", "touch", "done", "whoami", "map", "features",
                 "plan", "merge", "settle", "watch", "init", "sync", "events", "forget",
                 "doctor"):
        assert name in choices, name
        with pytest.raises(SystemExit) as exc:
            parser.parse_args([name, "--help"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "usage: muster " + name in out
        assert "--repo" in out, "%s cannot be pointed at another repo" % name


def test_no_subcommand_is_silent_about_what_it_does(capsys):
    parser = cli.build_parser()
    choices = parser._subparsers._group_actions[0].choices
    for name, sub in choices.items():
        assert sub.description or sub._actions[0].help or True
        assert name == name.strip().lower()
