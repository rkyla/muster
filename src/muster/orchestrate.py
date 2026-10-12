
"""The orchestrator: plan an integration, perform it in isolation, or split a
mixed working tree into reviewable lanes.

Safety stance, because this is the only module that writes:

* The user's working tree is never touched. Every merge and every settle happens
  in a throwaway `git worktree` under a temp directory.
* `--dry-run` is the default for anything that writes.
* A merge commits only if the configured `verify` command passes, and the merge is
  aborted if it does not.
* If the target branch is checked out somewhere, the result lands on a new
  `muster/*` branch instead of moving a branch out from under a running session.
* Success is confirmed by re-reading the ref, never inferred from "no error was
  raised".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from .gitio import Git, GitError, identity
from .model import now_iso
from .observe import cluster_changes, is_noise


@dataclass
class Plan:
    ref: str
    into: str
    verdict: str                      # clean | conflicts | empty | already-merged | error
    method: str = ""                  # merge-tree | scratch-worktree
    conflicts: list[str] = field(default_factory=list)
    auto_merged: list[str] = field(default_factory=list)
    ahead: int = 0
    behind: int = 0
    base_drift: int = 0
    notes: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    verify: str = ""
    lines: tuple = (0, 0)

    def to_dict(self):
        d = self.__dict__.copy()
        d["lines"] = list(self.lines)
        return d


def _safe(name):
    return name.replace("origin/", "").replace("/", "-")[:40]


def _tmp_root():
    return os.environ.get("MUSTER_TMPDIR") or tempfile.gettempdir()


def _scratch(git: Git, ref: str, branch: str | None = None, new_branch=False):
    """Create a throwaway worktree at `ref`, outside the repo. Caller removes it.

    new_branch=True uses `worktree add -b`. Pass an existing `branch` to check that
    branch out, so a commit made inside the worktree actually moves it. With neither,
    the worktree is detached and any commit made in it is unreachable - which is the
    silent-success bug this signature exists to prevent.
    """
    path = tempfile.mkdtemp(prefix="muster-wt-", dir=_tmp_root())
    os.rmdir(path)  # worktree add wants a path that does not exist
    args = ["worktree", "add"]
    if new_branch:
        args += ["-b", branch, path, ref]
    elif branch:
        args += [path, branch]
    else:
        args += ["--detach", path, ref]
    Git(git.repo).run(*args)
    return path


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #

def plan(git: Git, ref: str, into: str, verify: str = "") -> Plan:
    try:
        ref_sha = git.resolve(ref)
        into_sha = git.resolve(into)
    except GitError as exc:
        return Plan(ref=ref, into=into, verdict="error", notes=[str(exc)])
    if ref_sha == into_sha:
        return Plan(ref=ref, into=into, verdict="already-merged",
                    notes=["%s and %s point at the same commit" % (ref, into)])
    try:
        mb = git.merge_base(into_sha, ref_sha)
    except GitError as exc:
        return Plan(ref=ref, into=into, verdict="error",
                    notes=["no merge base between %s and %s: %s" % (ref, into, exc)])
    ahead, behind = git.ahead_behind(into_sha, ref_sha)
    if mb == ref_sha:
        return Plan(ref=ref, into=into, verdict="already-merged", ahead=ahead, behind=behind,
                    notes=["%s is an ancestor of %s; a merge would be a no-op" % (ref, into)])
    if ahead == 0:
        return Plan(ref=ref, into=into, verdict="empty", ahead=ahead, behind=behind,
                    notes=["%s has no commits that %s does not already have" % (ref, into)])

    supported, _clean, conflicted, _tree = git.merge_tree(into_sha, ref_sha)
    if supported:
        method, conflicts = "merge-tree", conflicted
    else:
        conflicts, _raw = _probe_scratch(git, into_sha, ref_sha)
        method = "scratch-worktree"

    touched = [l for l in git.run("diff", "--name-only", mb, ref_sha, check=False).splitlines()
               if l.strip()]
    auto = [p for p in touched if p not in conflicts]
    add = dele = 0
    for line in git.run("diff", "--numstat", mb, ref_sha, check=False).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                add += int(parts[0])
                dele += int(parts[1])
            except ValueError:
                pass

    p = Plan(ref=ref, into=into, verdict="clean" if not conflicts else "conflicts",
             method=method, conflicts=conflicts, auto_merged=auto, ahead=ahead,
             behind=behind, base_drift=behind, verify=verify, lines=(add, dele))
    if method == "scratch-worktree":
        p.notes.append("probed with a real merge in a throwaway worktree "
                       "(git %s has no merge-tree --write-tree)"
                       % ".".join(str(x) for x in git.version()))
    if behind:
        p.notes.append("%s has %d commit%s that %s lacks; expect the merge to carry them"
                       % (into, behind, "" if behind == 1 else "s", ref))
    if conflicts:
        p.steps.append("resolve %d conflicted file%s: %s"
                       % (len(conflicts), "" if len(conflicts) == 1 else "s",
                          ", ".join(conflicts[:6])))
    p.steps.append("merge %d commit%s (%d files, +%d/-%d) from %s into %s"
                   % (ahead, "" if ahead == 1 else "s", len(touched), add, dele, ref, into))
    if verify:
        p.steps.append("run verify: %s" % verify)
    else:
        p.notes.append("no verify command configured; the merge would commit unverified")
    p.steps.append("dry-run by default: add --apply to perform it")
    return p


def _probe_scratch(git: Git, into_sha, ref_sha):
    """A real merge in a throwaway worktree. Works on any git with worktrees."""
    path = None
    try:
        path = _scratch(git, into_sha)
        sub = Git(path)
        out = sub.run("merge", "--no-commit", "--no-ff", "--no-edit", ref_sha,
                      check=False, combine=True)
        conflicts = [l for l in sub.run("diff", "--name-only", "--diff-filter=U",
                                        check=False).splitlines() if l.strip()]
        sub.run("merge", "--abort", check=False)
        return conflicts, out
    except GitError as exc:
        return [], str(exc)
    finally:
        if path:
            git.worktree_remove(path)


# --------------------------------------------------------------------------- #
# performing a merge
# --------------------------------------------------------------------------- #

def merge(git: Git, ref: str, into: str, apply=False, verify="", force=False,
          ledger=None, session=None):
    p = plan(git, ref, into, verify=verify)
    result = {"plan": p.to_dict(), "applied": False, "branch": None, "log": []}
    if p.verdict == "error":
        result["log"].append("refusing: " + "; ".join(p.notes))
        return result
    if p.verdict in ("empty", "already-merged"):
        result["log"].append("nothing to do: " + "; ".join(p.notes))
        return result
    if p.conflicts and not force:
        result["log"].append("blocked: %d conflicted file(s). Resolve them, or pass --force "
                             "to merge with conflicts left in place." % len(p.conflicts))
        return result
    if not apply:
        result["log"].append("dry-run only; pass --apply to perform this merge")
        return result

    checked_out = {w.get("branch") for w in git.worktrees()}
    reuse = into not in checked_out
    if reuse:
        target = into
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = "muster/%s-into-%s-%s" % (_safe(ref), _safe(into), stamp)
        result["log"].append("%s is checked out in a worktree; integrating onto %s instead"
                             % (into, target))

    path = None
    try:
        if reuse:
            # Check `into` out for real. A detached worktree would commit into
            # nowhere and leave the branch exactly where it started, while every
            # earlier step still reported success.
            path = _scratch(git, into, branch=into)
        else:
            path = _scratch(git, into, branch=target, new_branch=True)
        sub = Git(path)
        # --no-commit, so verify runs against the merged tree while the merge is
        # still reversible. Committing first and rolling back later is not
        # rollback: a completed merge commit is history.
        # identity(): `git merge` resolves the committer up front, so a machine
        # with no git identity fails here, not at the commit.
        # combine=True: git reports the merge and its failures on stderr, and a
        # discarded stderr turns a failed merge into a silent no-op.
        out = sub.run(*identity(), "merge", "--no-commit", "--no-ff", "--no-edit", ref,
                      check=False, combine=True)
        result["log"].append(out.strip()[:1200] or "(git merge said nothing)")
        unresolved = [l for l in sub.run("diff", "--name-only", "--diff-filter=U",
                                         check=False).splitlines() if l.strip()]
        if unresolved:
            sub.run("merge", "--abort", check=False)
            result["log"].append("aborted: %d unresolved conflict(s) even with --force"
                                 % len(unresolved))
            result["branch"] = target
            return result

        if verify:
            proc = subprocess.run(verify, shell=True, cwd=path,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            tail = proc.stdout.decode("utf-8", "replace")[-2000:]
            if proc.returncode != 0:
                sub.run("merge", "--abort", check=False)
                result["log"].append("verify failed (%s); merge aborted. Output tail:\n%s"
                                     % (proc.returncode, tail))
                return result
            result["log"].append("verify passed: %s" % verify)

        done = sub.run(*identity(), "commit", "--no-edit", check=False, combine=True)
        if sub.run("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).strip():
            result["log"].append("commit after verify failed: %s" % done.strip()[:300])
            sub.run("merge", "--abort", check=False)
            return result

        sha = sub.run("rev-parse", "HEAD").strip()
        # Confirm the ref actually moved before claiming success.
        moved = git.run("rev-parse", "-q", "--verify", "refs/heads/" + target,
                        check=False).strip()
        if moved != sha:
            result["log"].append("FAILED: the merge produced %s but refs/heads/%s is %s; "
                                 "nothing was integrated"
                                 % (sha[:9], target, (moved or "missing")[:9]))
            result["branch"] = target
            return result
        result["applied"] = True
        result["branch"] = target
        result["sha"] = sha
        result["log"].append("merged %s onto %s at %s" % (ref, target, sha[:9]))
        if ledger:
            ledger.record("merge", session_id=session, ref=ref, into=into,
                          branch=target, sha=sha, verified=bool(verify))
    except GitError as exc:
        result["log"].append("merge failed: %s" % exc)
    finally:
        if path:
            git.worktree_remove(path)
    return result


# --------------------------------------------------------------------------- #
# settling a mixed working tree into lanes
# --------------------------------------------------------------------------- #

@dataclass
class SettlePlan:
    base: str
    branches: list[dict] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def settle_plan(git: Git, snap, base=None, only=None, max_clusters=12):
    wt = snap.head_worktree()
    sp = SettlePlan(base=base or snap.base)
    if not wt or not wt.dirty:
        sp.notes.append("working tree is clean; nothing to settle")
        return sp
    clusters = [c for c in (snap.clusters or cluster_changes(wt.dirty))
                if any(not is_noise(p) for p in c.paths)]
    if only:
        clusters = [c for c in clusters if c.name in only or set(c.paths) & set(only)]
    clusters = clusters[:max_clusters]
    if not clusters:
        sp.notes.append("every dirty path is ignored noise; nothing to settle")
        return sp

    # First lane to claim a path wins; anything shared is reported rather than
    # committed twice or dropped without a word.
    claimed = {}
    for c in clusters:
        paths = []
        for path in c.paths:
            if path in claimed:
                sp.skipped.append("%s: in both %s and %s - assign it to one lane by hand"
                                  % (path, claimed[path], c.name))
                continue
            claimed[path] = c.name
            paths.append(path)
        if not paths:
            continue
        branch = "muster/%s-%s" % (_safe(c.name).lower().replace(" ", "-")[:40],
                                   time.strftime("%m%d-%H%M%S"))
        sp.branches.append({
            "branch": branch, "cluster": c.name, "paths": paths,
            "confidence": c.confidence, "reason": c.reason,
            "message": _settle_message(c),
        })
    sp.notes.append("%d lane(s) from %d dirty path(s); base %s"
                    % (len(sp.branches), sum(len(b["paths"]) for b in sp.branches), sp.base))
    return sp


def _settle_message(cluster):
    head = "wip(%s): %d file%s from the shared working tree" % (
        cluster.name[:40], len(cluster.paths), "" if len(cluster.paths) == 1 else "s")
    body = [
        "Grouped by muster: %s" % cluster.reason,
        "Confidence: %s" % cluster.confidence,
        "",
        "Files:",
    ] + ["  %s" % p for p in cluster.paths[:40]]
    body += ["", "Split out of an uncommitted working tree; not yet reviewed."]
    return head + "\n\n" + "\n".join(body)


def settle_apply(git: Git, sp: SettlePlan, apply=False, ledger=None, session=None,
                 source_worktree=None):
    source = os.path.abspath(source_worktree or git.toplevel())
    result = {"applied": False, "created": [], "failed": [], "notes": list(sp.notes),
              "skipped": list(sp.skipped)}
    if not sp.branches:
        return result
    if not apply:
        result["notes"].append("dry-run: pass --apply to create these branches")
        return result
    try:
        base_sha = git.resolve(sp.base)
    except GitError as exc:
        result["failed"].append("base %s unresolvable: %s" % (sp.base, exc))
        return result

    for entry in sp.branches:
        path = None
        try:
            path = _scratch(git, sp.base, branch=entry["branch"], new_branch=True)
            sub = Git(path)
            staged = 0
            for rel in entry["paths"]:
                src = os.path.join(source, rel)
                dst = os.path.join(path, rel)
                if os.path.exists(src):
                    os.makedirs(os.path.dirname(dst) or path, exist_ok=True)
                    shutil.copy2(src, dst)
                    sub.run("add", "--", rel, check=False)
                    staged += 1
                else:
                    # present in the base, deleted in the working tree
                    sub.run("add", "-A", "--", rel, check=False)
                    staged += 1
            if staged == 0:
                result["failed"].append("%s: no file could be staged" % entry["branch"])
                continue
            sub.run(*identity(), "commit", "-m", entry["message"],
                        "--no-verify", check=False)
            sha = sub.run("rev-parse", "HEAD", check=False).strip()
            moved = git.run("rev-parse", "-q", "--verify",
                            "refs/heads/" + entry["branch"], check=False).strip()
            if not sha or moved != sha:
                result["failed"].append("%s: commit did not create the branch"
                                        % entry["branch"])
                continue
            result["created"].append({"branch": entry["branch"], "sha": sha[:9],
                                      "cluster": entry["cluster"], "files": staged})
            if ledger:
                ledger.record("settle", session_id=session, branch=entry["branch"],
                              cluster=entry["cluster"], files=staged)
        except GitError as exc:
            result["failed"].append("%s: %s" % (entry["branch"], exc))
        finally:
            if path:
                git.worktree_remove(path)
    result["applied"] = bool(result["created"])
    return result


# --------------------------------------------------------------------------- #
# watch loop
# --------------------------------------------------------------------------- #

def diff_snapshots(old, new):
    """What changed between two observations. Used by watch and by tests."""
    events = []
    if not old:
        return events
    old_refs = {r.name: r.sha for r in old.refs}
    new_refs = {r.name: r.sha for r in new.refs}
    for name in sorted(set(new_refs) - set(old_refs)):
        events.append({"kind": "ref-new", "ref": name})
    for name in sorted(set(old_refs) - set(new_refs)):
        events.append({"kind": "ref-gone", "ref": name})
    for name in sorted(set(old_refs) & set(new_refs)):
        if old_refs[name] != new_refs[name]:
            events.append({"kind": "ref-moved", "ref": name,
                           "from": old_refs[name][:9], "to": new_refs[name][:9]})
    owt, nwt = old.head_worktree(), new.head_worktree()
    od = {f.path for f in owt.dirty} if owt else set()
    nd = {f.path for f in nwt.dirty} if nwt else set()
    for path in sorted(nd - od):
        events.append({"kind": "file-dirtied", "path": path})
    for path in sorted(od - nd):
        events.append({"kind": "file-cleaned", "path": path})
    ocol = {(c.path, c.a, c.b, c.level) for c in old.collisions}
    ncol = {(c.path, c.a, c.b, c.level) for c in new.collisions}
    for path, a, b, level in sorted(ncol - ocol):
        if level in ("same-hunk", "overlapping"):
            events.append({"kind": "collision-new", "path": path, "a": a, "b": b,
                           "level": level})
    return events


def watch(repo=None, interval=30, iterations=None, notify="", on_event=None, base=None):
    """Observation loop. Emits an event whenever another lane moves."""
    from .observe import build_snapshot
    prev = None
    count = 0
    while iterations is None or count < iterations:
        snap, _ledger = build_snapshot(repo=repo, base=base)
        for ev in diff_snapshots(prev, snap):
            ev["at"] = now_iso()
            if on_event:
                on_event(ev, snap)
            if notify:
                subprocess.run(notify, shell=True,
                               input=(ev["kind"] + " " + str(ev)).encode(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               check=False)
        prev = snap
        count += 1
        if iterations is not None and count >= iterations:
            break
        time.sleep(interval)
    return prev
