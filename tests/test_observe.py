
"""Observation: refs, worktrees, and the clustering of a mixed working tree."""
import os
import time

from muster.observe import build_snapshot, cluster_changes, is_noise
from muster.model import FileChange


def _paths(clusters):
    return {p for c in clusters for p in c.paths}


def test_refs_report_ahead_and_behind(snapshot):
    upload = snapshot.ref("feature/upload-api")
    assert upload is not None
    assert upload.is_head
    assert upload.ahead == 2           # feat(upload) and feat(site)
    assert upload.behind == 2          # main moved on with the readme merge
    assert any(c["subject"].startswith("feat(upload)") for c in upload.commits)


def test_merged_branch_is_flagged_not_listed_as_work(snapshot):
    readme = snapshot.ref("chore/readme")
    assert readme is not None
    assert readme.merged_into_base is True


def test_dirty_tree_is_observed_without_any_claims(snapshot):
    wt = snapshot.head_worktree()
    paths = {f.path for f in wt.dirty}
    assert "site/hero.jsx" in paths
    assert "site/pricing.jsx" in paths
    assert "notes.txt" in paths
    deleted = {f.path for f in wt.dirty if f.status == "D"}
    assert "site/footer.jsx" in deleted


def test_binary_untracked_file_is_not_counted_as_lines(snapshot):
    blob = [f for f in snapshot.head_worktree().dirty
            if f.path == "experiments/blob.bin"]
    assert blob, "the binary file should still be observed"
    assert blob[0].lines_added == -1, "binary content must not be reported as +N lines"


def test_new_directory_becomes_one_high_confidence_lane(snapshot):
    lanes = [c for c in snapshot.clusters if c.name == "experiments"]
    assert len(lanes) == 1
    lane = lanes[0]
    assert lane.confidence == "high"
    assert set(lane.paths) == {"experiments/run.py", "experiments/notebooks/probe.py",
                               "experiments/blob.bin"}
    assert "is new" in lane.reason


def test_lanes_edited_days_apart_do_not_merge(snapshot):
    """The exact false positive that made an early version useless."""
    site = [p for c in snapshot.clusters for p in c.paths if p.startswith("site/")]
    exp = [p for c in snapshot.clusters for p in c.paths if p.startswith("experiments/")]
    assert site and exp
    assert not (set(site) & set(exp))
    names = {c.name for c in snapshot.clusters}
    assert not any("site" in n and "experiments" in n for n in names)


def test_deleted_file_joins_its_directory_not_its_head_timestamp(snapshot):
    lane = [c for c in snapshot.clusters if "site/footer.jsx" in c.paths][0]
    assert "site/hero.jsx" in lane.paths
    assert lane.last_mtime > 0
    # HEAD saw footer.jsx long before it was deleted; the lane must not claim that span
    assert (lane.last_mtime - lane.first_mtime) < 6 * 3600


def test_undated_and_unrelated_file_stays_low_confidence(snapshot):
    lane = [c for c in snapshot.clusters if "notes.txt" in c.paths][0]
    assert lane.confidence == "low"


def test_clusters_never_lose_a_dirty_file(snapshot):
    wt = snapshot.head_worktree()
    real = {f.path for f in wt.dirty if not is_noise(f.path)}
    assert _paths(snapshot.clusters) == real


def test_empty_working_tree_yields_no_clusters_and_says_so(tmp_path, repo):
    from muster.gitio import Git
    Git(repo).run("checkout", "-q", "--", ".")
    Git(repo).run("clean", "-qfd")
    snap, _ = build_snapshot(repo=repo)
    assert snap.clusters == [], "a clean tree has no lanes"
    assert not [c for c in snap.collisions if "working-tree" in (c.a, c.b)], \
        "nothing uncommitted means nothing to clash with the tree"
    # branch-vs-branch risk is still real with a clean tree
    assert any({c.a, c.b} == {"feature/upload-api", "feature/billing"} for c in snap.collisions)


def test_snapshot_round_trips_through_json(snapshot):
    again = type(snapshot).from_dict(snapshot.to_dict())
    assert again.repo == snapshot.repo
    assert [c.name for c in again.clusters] == [c.name for c in snapshot.clusters]
    assert [r.name for r in again.refs] == [r.name for r in snapshot.refs]
    assert again.ref("feature/billing").ahead == snapshot.ref("feature/billing").ahead


def test_warnings_are_present_when_nothing_is_found(tmp_path):
    os.makedirs(str(tmp_path / "plain"))
    from muster.gitio import GitError
    try:
        build_snapshot(repo=str(tmp_path / "plain"))
    except GitError as exc:
        assert "not a git repository" in str(exc)
    else:
        raise AssertionError("a non-repo must raise, not return an empty snapshot")


def _add_and_age(repo, rel, hours_ago, content="x\n"):
    """Create a file and give it an mtime, the way a real session leaves one."""
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)
    stamp = time.time() - hours_ago * 3600
    os.utime(path, (stamp, stamp))
    return path


def _lanes_of(repo):
    from muster.gitio import Git
    from muster.observe import cluster_changes, collect_worktrees
    wt = collect_worktrees(Git(repo), [])[0]
    return cluster_changes(wt.dirty, window=6 * 3600, new_roots=wt.new_roots)


def test_a_state_file_named_after_a_new_directory_joins_that_lane(repo):
    """`.brag_run_root.json` configures `brag-2026-10-12-090000/` from the root.

    Directory affinity alone welded unrelated lanes together, so this rule fires
    only on a distinctive shared word, and only when exactly one lane can claim it.
    """
    _add_and_age(repo, "brag-2026-10-12-090000/frame.png", 8)
    _add_and_age(repo, ".brag_run_root.json", 9, "{}\n")
    brag = [c for c in _lanes_of(repo) if c.name.startswith("brag")]
    assert len(brag) == 1, [c.name for c in _lanes_of(repo)]
    assert ".brag_run_root.json" in brag[0].paths


def test_an_unrelated_root_file_stays_its_own_lane(repo):
    _add_and_age(repo, "brag-2026-10-12-090000/frame.png", 8)
    _add_and_age(repo, "unrelated_scratch.py", 20)   # a different sitting
    lanes = _lanes_of(repo)
    brag = [c for c in lanes if c.name.startswith("brag")]
    assert len(brag) == 1
    assert "unrelated_scratch.py" not in brag[0].paths
    assert "unrelated_scratch.py" in _paths(lanes), "a file must never be dropped"


def test_a_word_two_lanes_share_does_not_merge_them(repo):
    """Ambiguity must leave both lanes alone rather than pick one."""
    _add_and_age(repo, "marketing-2026-10-12/a.png", 3)
    _add_and_age(repo, "marketing-2026-10-11/b.png", 20)   # a different sitting
    _add_and_age(repo, "marketing_notes.md", 9)            # between the two
    lanes = _lanes_of(repo)
    assert len([c for c in lanes if c.name.startswith("marketing")]) == 2
    assert "marketing_notes.md" in _paths(lanes)
