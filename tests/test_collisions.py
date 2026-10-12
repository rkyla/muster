
"""Collision detection at line level, not file level."""
from muster.gitio import Git
from muster.observe import _overlap, find_collisions
from muster.model import Collision


def test_overlap_ranges():
    assert _overlap([[10, 20]], [[15, 25]]) == (True, True)
    assert _overlap([[10, 11]], [[12, 20]]) == (False, True)
    assert _overlap([[10, 12]], [[50, 60]]) == (False, False)
    assert _overlap([], [[1, 2]]) == (False, False)


def test_two_branches_editing_the_same_region_are_high(repo):
    """upload() and charge() are both appended to the end of app.py."""
    snap, _ = _snap(repo)
    hits = [c for c in snap.collisions
            if c.path == "app.py" and {c.a, c.b} == {"feature/upload-api", "feature/billing"}]
    assert hits, "two lanes appending to the same file must be reported"
    assert hits[0].severity == "high"
    assert hits[0].level == "same-hunk"


def test_head_branch_is_not_a_collision_with_its_own_working_tree(repo):
    """The working tree is measured against HEAD; overlapping HEAD is normal."""
    snap, _ = _snap(repo)
    assert not [c for c in snap.collisions
                if c.b == "working-tree" and c.a == "feature/upload-api"
                and c.level == "same-hunk"]


def test_inferred_lanes_do_not_collide_with_themselves(repo):
    snap, _ = _snap(repo)
    assert not [c for c in snap.collisions
                if c.a.startswith("lane:") and c.b == "working-tree"]


def test_declared_scope_over_a_dirty_file_is_reported(repo):
    from muster.model import Session
    from muster.store import Ledger
    Ledger(repo).upsert_session(Session(id="intruder", harness="claude-code",
                                        intent="site refresh", paths=["site"], status="active"))
    snap, _ = _snap(repo)
    hits = [c for c in snap.collisions if c.a == "intruder"]
    assert hits, "a declared scope must surface against the tree"
    assert {c.path for c in hits} >= {"site/hero.jsx", "site/pricing.jsx"}


def test_two_sessions_declaring_the_same_scope_collide_before_editing(repo):
    from muster.model import Session
    from muster.store import Ledger
    led = Ledger(repo)
    led.upsert_session(Session(id="claude-code/one", intent="uploads", paths=["app.py"]))
    led.upsert_session(Session(id="opencode/two", intent="billing", paths=["app.py", "billing.py"]))
    snap, _ = _snap(repo)
    hits = [c for c in snap.collisions
            if {c.a, c.b} == {"claude-code/one", "opencode/two"}]
    assert hits and hits[0].severity == "high"


def test_touch_reports_another_sessions_scope_even_when_the_file_is_clean(repo):
    from muster.brief import verdict_for
    from muster.model import Session
    from muster.store import Ledger
    Ledger(repo).upsert_session(Session(id="opencode/two", intent="billing",
                                        paths=["app.py"], status="active"))
    snap, _ = _snap(repo)
    res = verdict_for(snap, ["app.py"], me="claude-code/one")
    assert res["verdict"] in ("medium", "high")
    assert res["files"][0]["owners"] == ["opencode/two"]
    clean = verdict_for(snap, ["util.py"], me="claude-code/one")
    assert clean["verdict"] == "safe"


def _snap(repo):
    from muster.observe import build_snapshot
    return build_snapshot(repo=repo, window=6 * 3600)
