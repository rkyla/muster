
"""The brief an agent reads, and the touch verdict."""
import json

from muster.brief import render_brief, render_map, render_verdict, verdict_for
from muster.model import Session
from muster.store import Ledger


def test_brief_lists_uncommitted_lanes_and_branches(snapshot):
    text = render_brief(snapshot, me="tester")
    assert "UNCOMMITTED WORK IN THIS WORKING TREE" in text
    assert "experiments" in text
    assert "OTHER BRANCHES" in text
    assert "feature/billing" in text


def test_brief_says_none_rather_than_omitting_the_section(repo, tmp_path):
    from muster.gitio import Git
    git = Git(repo)
    git.run("checkout", "-q", "--", ".")
    git.run("clean", "-qfd")
    from muster.observe import build_snapshot
    snap, _ = build_snapshot(repo=repo)
    text = render_brief(snap, me="tester")
    assert "UNCOMMITTED WORK IN THIS WORKING TREE - none" in text


def test_brief_json_round_trips(snapshot):
    payload = json.loads(render_brief(snapshot, me="tester", fmt="json"))
    assert payload["me"] == "tester"
    assert payload["repo"] == snapshot.repo
    assert {r["name"] for r in payload["refs"]} >= {"feature/billing", "main"}


def test_brief_labels_inferred_lanes_as_inferred(snapshot):
    text = render_brief(snapshot, me="tester")
    assert "attribution inferred" in text


def test_brief_advises_claiming_when_nothing_is_declared(snapshot):
    assert "muster claim" in render_brief(snapshot, me="tester")


def test_brief_shares_a_declared_intent(repo):
    Ledger(repo).upsert_session(Session(id="claude-code/one", harness="claude-code",
                                        intent="pricing page refresh",
                                        paths=["site"], status="active"))
    from muster.observe import build_snapshot
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    text = render_brief(snap, me="someone-else")
    assert "pricing page refresh" in text
    assert "DECLARED SESSIONS" in text


def test_touch_safe_for_an_untouched_file(snapshot):
    res = verdict_for(snapshot, ["util.py"], me="tester")
    assert res["verdict"] == "safe"
    assert render_verdict(res).startswith("SAFE")


def test_touch_flags_a_file_another_lane_rewrote(repo):
    from muster.observe import build_snapshot
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    res = verdict_for(snap, ["app.py"], me="tester")
    assert res["verdict"] in ("high", "medium")
    assert render_verdict(res).startswith(("STOP", "CAUTION"))


def test_map_lists_every_collision_with_both_sides(snapshot):
    text = render_map(snapshot)
    assert "feature/upload-api" in text and "feature/billing" in text
    assert "collision(s)" in text


def test_map_of_a_quiet_repo_says_so(tmp_path, repo):
    from muster.gitio import Git
    from muster.observe import build_snapshot
    git = Git(repo)
    git.run("branch", "lonely", "feature/upload-api")
    git.run("branch", "-D", "feature/billing")
    git.run("branch", "-D", "chore/readme")
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    if not snap.collisions:
        assert render_map(snap) == "no collisions observed"


def test_your_own_unattributed_file_is_not_a_warning(snapshot):
    """An inferred lane in your own tree may be your own work.

    Escalating it to CAUTION makes `muster touch` exit non-zero for the common
    case of editing a file you already edited, and agents stop trusting it.
    """
    wt = snapshot.head_worktree()
    own = sorted(f.path for f in wt.dirty)[0]
    res = verdict_for(snapshot, [own], me="tester")
    assert res["verdict"] == "low", (own, res["files"][0]["reasons"])
    assert render_verdict(res).startswith("FYI")


def test_a_declared_other_session_does_escalate(repo):
    from muster.observe import build_snapshot
    from muster.store import Ledger
    from muster.model import Session, Claim
    led = Ledger(repo)
    led.upsert_session(Session(id="codex/pricing", harness="codex",
                               intent="pricing page", paths=["site"], source="declared"))
    led.add_claim(Claim(session_id="codex/pricing", paths=["site"], intent="pricing page"))
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    res = verdict_for(snap, ["site/hero.jsx"], me="tester")
    assert res["verdict"] == "medium", res
    assert render_verdict(res).startswith("CAUTION")
    assert any("codex/pricing declared" in r for f in res["files"] for r in f["reasons"])
