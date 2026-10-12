
"""The orchestrator. The only module allowed to write, so the most watched."""
import os

from muster.gitio import Git
from muster.orchestrate import diff_snapshots, merge, plan, settle_apply, settle_plan
from muster.observe import build_snapshot


def _head(repo):
    return Git(repo).run("rev-parse", "HEAD").strip()


def test_plan_reports_clean_merge(repo):
    p = plan(Git(repo), "chore/readme", "main")
    assert p.verdict in ("already-merged", "clean")


def test_plan_predicts_the_app_py_conflict(repo):
    p = plan(Git(repo), "feature/billing", "feature/upload-api")
    assert p.verdict == "conflicts"
    assert "app.py" in p.conflicts
    assert p.method in ("merge-tree", "scratch-worktree")
    assert p.ahead >= 1 and p.lines[0] > 0


def test_plan_of_an_ancestor_is_already_merged(repo):
    git = Git(repo)
    git.run("branch", "first-commit", git.run("rev-list", "--max-parents=0", "HEAD").strip())
    assert plan(git, "first-commit", "main").verdict == "already-merged"


def test_plan_of_an_unknown_ref_is_an_error_not_an_empty_plan(repo):
    p = plan(Git(repo), "feature/does-not-exist", "main")
    assert p.verdict == "error"
    assert p.notes, "an error must carry the reason"


def test_plan_records_missing_verify_as_a_note(repo):
    p = plan(Git(repo), "feature/billing", "main", verify="")
    assert any("no verify command" in n for n in p.notes)
    p2 = plan(Git(repo), "feature/billing", "main", verify="true")
    assert any("verify" in s for s in p2.steps)


def test_merge_is_dry_run_by_default_and_writes_nothing(repo):
    before = _head(repo)
    res = merge(Git(repo), "feature/upload-api", "main", apply=False)
    assert res["applied"] is False
    assert _head(repo) == before
    assert any("dry-run" in line for line in res["log"])


def test_merge_reports_a_no_op_honestly(repo):
    res = merge(Git(repo), "chore/readme", "main", apply=False)
    assert res["plan"]["verdict"] == "already-merged"
    assert any("nothing to do" in line for line in res["log"])


def test_merge_apply_moves_a_branch_that_is_not_checked_out(repo):
    git = Git(repo)
    git.run("branch", "integration", "main")
    before = git.run("rev-parse", "integration").strip()
    res = merge(git, "feature/upload-api", "integration", apply=True)
    assert res["applied"] is True, res["log"]
    assert res["branch"] == "integration"
    after = git.run("rev-parse", "integration").strip()
    assert after != before
    assert git.run("merge-base", "--is-ancestor", "feature/upload-api", "integration",
                   check=False) == ""


def test_merge_onto_a_new_branch_when_the_target_is_checked_out(repo, tmp_path):
    """main is live in a second worktree, so it must not be moved underneath it."""
    git = Git(repo)
    other = str(tmp_path / "wt-main")
    git.run("worktree", "add", "-q", other, "main")
    try:
        before = git.run("rev-parse", "main").strip()
        res = merge(git, "feature/upload-api", "main", apply=True)
        assert res["applied"] is True, res["log"]
        assert res["branch"].startswith("muster/")
        assert git.run("rev-parse", "main").strip() == before, "a live branch must not move"
    finally:
        git.worktree_remove(other)


def test_merge_refuses_conflicts_without_force(repo):
    res = merge(Git(repo), "feature/billing", "feature/upload-api", apply=True)
    assert res["applied"] is False
    assert any("blocked" in line for line in res["log"])


def test_merge_does_not_touch_the_working_tree_when_blocked(repo):
    git = Git(repo)
    dirty_before = {p for p in git.status() if True}
    res = merge(git, "feature/billing", "feature/upload-api", apply=True)
    assert res["applied"] is False
    assert {p for p in git.status()} == dirty_before


def test_merge_aborts_when_verify_fails(repo):
    git = Git(repo)
    git.run("branch", "integration", "main")
    before = git.run("rev-parse", "integration").strip()
    res = merge(git, "feature/upload-api", "integration", apply=True, verify="exit 1")
    assert res["applied"] is False
    assert any("verify failed" in line for line in res["log"])
    assert git.run("rev-parse", "integration").strip() == before, \
        "a failed verify must leave the branch exactly where it was"


def test_merge_runs_verify_and_commits_when_it_passes(repo):
    git = Git(repo)
    git.run("branch", "integration", "main")
    res = merge(git, "feature/upload-api", "integration", apply=True,
                verify="test -f README.md")
    assert res["applied"] is True
    assert any("verify passed" in line for line in res["log"])


def test_verify_runs_inside_the_isolated_worktree_not_the_repo(repo):
    """The verify command must see the merged result, not the user's dirty tree."""
    git = Git(repo)
    git.run("branch", "integration", "main")
    # billing.py exists only on feature/billing; the user's tree sits on
    # feature/upload-api and has no such file, so a passing verify proves the
    # command ran against the merged worktree and not the user's checkout.
    assert not os.path.exists(os.path.join(repo, "billing.py"))
    res = merge(git, "feature/billing", "integration", apply=True,
                verify="test -f billing.py")
    assert res["applied"] is True, res["log"]
    assert not os.path.exists(os.path.join(repo, "billing.py")), \
        "the merge must not have leaked into the user's working tree"


def test_verify_failure_is_reported_with_its_output(repo):
    git = Git(repo)
    git.run("branch", "integration", "main")
    res = merge(git, "feature/upload-api", "integration", apply=True,
                verify="echo 'boom: 1 failed' >&2; exit 3")
    assert res["applied"] is False
    joined = "\n".join(res["log"])
    assert "boom: 1 failed" in joined


def test_merge_leaves_no_worktrees_behind(repo):
    git = Git(repo)
    git.run("branch", "integration", "main")
    before = len(git.worktrees())
    merge(git, "feature/upload-api", "integration", apply=True, verify="exit 1")
    merge(git, "feature/billing", "integration", apply=True)
    merge(git, "feature/upload-api", "integration", apply=True)
    assert len(git.worktrees()) == before


# ---- settle --------------------------------------------------------------- #

def test_settle_proposes_one_branch_per_lane(repo):
    git = Git(repo)
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    sp = settle_plan(git, snap, base="main")
    names = " ".join(b["cluster"] for b in sp.branches)
    assert "experiments" in names
    assert any("site" in b["cluster"] or "hero" in b["cluster"] for b in sp.branches)
    for b in sp.branches:
        assert b["message"].startswith("wip(")
        assert "Grouped by muster" in b["message"]


def test_settle_dry_run_creates_no_branches(repo):
    git = Git(repo)
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    sp = settle_plan(git, snap, base="main")
    res = settle_apply(git, sp, apply=False)
    assert res["created"] == []
    assert not [r for r in git.run("for-each-ref", "refs/heads/muster", check=False).split()]


def test_settle_apply_creates_branches_and_leaves_the_tree_alone(repo):
    git = Git(repo)
    dirty_before = sorted(git.status())
    head_before = _head(repo)
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    sp = settle_plan(git, snap, base="main")
    res = settle_apply(git, sp, apply=True)
    assert res["created"], res["failed"]
    assert sorted(git.status()) == dirty_before, "settle must not touch the working tree"
    assert _head(repo) == head_before
    for made in res["created"]:
        assert git.run("rev-parse", "--verify", "-q", made["branch"]).strip()
        files = git.run("diff", "--name-only", "main", made["branch"]).split()
        assert files, "each settle branch must carry its lane"


def test_settle_branch_content_matches_the_lane(repo):
    git = Git(repo)
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    sp = settle_plan(git, snap, base="main")
    exp = [b for b in sp.branches if b["cluster"] == "experiments"][0]
    res = settle_apply(git, sp, apply=True)
    made = [m for m in res["created"] if m["cluster"] == "experiments"][0]
    files = set(git.run("diff", "--name-only", "main", made["branch"]).split())
    assert files == {"experiments/run.py", "experiments/notebooks/probe.py",
                     "experiments/blob.bin"}


def test_settle_reports_a_file_two_lanes_both_claim(repo):
    from muster.model import Cluster
    from muster.orchestrate import SettlePlan
    git = Git(repo)
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    snap.clusters.append(Cluster(name="impostor", paths=["site/hero.jsx", "notes.txt"],
                                 reason="test", confidence="low"))
    sp = settle_plan(git, snap, base="main")
    assert any("hero.jsx" in s for s in sp.skipped)


# ---- watch ---------------------------------------------------------------- #

def test_diff_detects_a_moved_ref_and_a_new_dirty_file(repo):
    git = Git(repo)
    first, _ = build_snapshot(repo=repo, window=6 * 3600)
    with open(os.path.join(repo, "brand_new.py"), "w") as fh:
        fh.write("x = 1\n")
    git.run("checkout", "-qb", "feature/late")
    second, _ = build_snapshot(repo=repo, window=6 * 3600)
    kinds = {e["kind"] for e in diff_snapshots(first, second)}
    assert "ref-new" in kinds
    assert "file-dirtied" in kinds


def test_diff_detects_a_branch_being_rewritten(repo):
    git = Git(repo)
    first, _ = build_snapshot(repo=repo, window=6 * 3600)
    git.run("branch", "-f", "feature/billing", "HEAD")
    second, _ = build_snapshot(repo=repo, window=6 * 3600)
    moved = [e for e in diff_snapshots(first, second) if e["kind"] == "ref-moved"]
    assert moved and moved[0]["ref"] == "feature/billing"


def test_diff_of_identical_snapshots_is_empty(repo):
    a, _ = build_snapshot(repo=repo, window=6 * 3600)
    b, _ = build_snapshot(repo=repo, window=6 * 3600)
    assert diff_snapshots(a, b) == []


def test_a_fast_forwardable_merge_still_runs_verify(repo):
    """A merge git could fast-forward must not skip the verify step.

    With `--no-commit` git leaves the result staged instead of moving the ref, so
    verify sees the merged tree and a failure still rolls everything back.
    """
    git = Git(repo)
    seed = git.run("rev-list", "--max-parents=0", "HEAD").strip()
    git.run("branch", "ff-target", seed)
    before = git.run("rev-parse", "ff-target").strip()
    res = merge(git, "feature/upload-api", "ff-target", apply=True, verify="exit 1")
    assert res["applied"] is False, res["log"]
    assert git.run("rev-parse", "ff-target").strip() == before, \
        "a fast-forward must not move the branch past a failing verify"
    assert any("verify failed" in line for line in res["log"])


def test_a_fast_forwardable_merge_applies_when_verify_passes(repo):
    git = Git(repo)
    seed = git.run("rev-list", "--max-parents=0", "HEAD").strip()
    git.run("branch", "ff-target", seed)
    res = merge(git, "feature/upload-api", "ff-target", apply=True,
                verify="test -f docs/upload.md")
    assert res["applied"] is True, res["log"]
    assert git.run("merge-base", "--is-ancestor", "feature/upload-api", "ff-target",
                   check=False) == ""


def test_a_merge_that_fails_is_reported_and_not_applied(repo):
    """Unrelated histories: git refuses, and muster must not call that a merge."""
    git = Git(repo)
    # Built with plumbing so the user's dirty working tree is not disturbed.
    blob = git.run("hash-object", "-w", "--stdin", stdin=b"nothing in common\n").strip()
    tree = git.run("mktree", stdin=("100644 blob %s\telsewhere.txt\n" % blob).encode()).strip()
    from muster.gitio import identity
    orphan = git.run(*identity(), "commit-tree", tree, "-m", "orphan start").strip()
    git.run("branch", "unrelated", orphan)
    res = merge(git, "unrelated", "main", apply=True)
    assert res["applied"] is False, res["log"]
    joined = "\n".join(res["log"]).lower()
    assert "unrelated histories" in joined or "refusing" in joined, res["log"]
