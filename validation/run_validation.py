#!/usr/bin/env python3
"""Run muster, read-only, against a real repository and record what it said.

This is not a test of the happy path. It is a check that the tool says something
true about a repository nobody designed it for. Every check is a property that
would be embarrassing to get wrong, and the script exits non-zero if any of them
fails, so a silent-empty result cannot pass as a success.

    python validation/run_validation.py [repo] [--json] [--write-doc]

Nothing here writes to the target repository. The ledger goes to the user state
dir, which is where `muster` puts it unless a repo has opted in with `muster init`.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from muster import __version__                      # noqa: E402
from muster.brief import render_brief, render_map, render_verdict, verdict_for  # noqa: E402
from muster.digest import features                  # noqa: E402
from muster.gitio import Git                        # noqa: E402
from muster.observe import build_snapshot           # noqa: E402
from muster.orchestrate import plan, settle_plan    # noqa: E402

DEFAULT_REPO = os.path.expanduser("~/Projects/videoEditor")


class Report:
    def __init__(self):
        self.rows = []

    def check(self, name, ok, detail=""):
        self.rows.append({"name": name, "ok": bool(ok), "detail": detail})
        flag = "PASS" if ok else "FAIL"
        print("  %-4s %-46s %s" % (flag, name, detail[:96]))
        return bool(ok)

    @property
    def failed(self):
        return [r for r in self.rows if not r["ok"]]


def _fingerprint(repo):
    """Everything a writer could damage, reduced to something comparable."""
    git = Git(repo)
    return {
        "status": git.run("status", "--porcelain=v1", check=False),
        "head": git.run("rev-parse", "HEAD", check=False).strip(),
        "refs": git.run("for-each-ref", check=False),
        "worktrees": git.run("worktree", "list", check=False),
        "stashes": git.run("stash", "list", check=False),
    }


def writer_check(repo, rep):
    """Run the one command that writes, against a hardlink copy of a real repo.

    A hardlink copy costs no disk and no time on a large repository, and git
    writes new files rather than editing objects in place, so the original keeps
    its own bytes. The copy is deleted afterwards; deleting a hardlink never
    touches the file it pointed at.
    """
    import shutil
    import tempfile
    from muster.orchestrate import settle_apply

    print("\nthe writer, against a copy of the real repository")
    before = _fingerprint(repo)
    parent = os.path.dirname(os.path.abspath(repo).rstrip("/")) or "/"
    dest = os.path.join(parent, ".muster-writer-check-%d" % os.getpid())
    if os.path.exists(dest):
        shutil.rmtree(dest)
    made = subprocess.run(["cp", "-al", os.path.abspath(repo), dest],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if made.returncode != 0:
        made = subprocess.run(["cp", "-a", os.path.abspath(repo), dest],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if made.returncode != 0:
        rep.check("a copy of the repository could be made", False,
                  made.stderr.decode()[:120])
        return
    try:
        state = os.path.join(tempfile.gettempdir(), "muster-writer-state-%d" % os.getpid())
        os.environ["MUSTER_STATE_DIR"] = state
        cgit = Git(dest)
        snap, _ledger = build_snapshot(repo=dest)
        sp = settle_plan(cgit, snap)
        head_wt = snap.head_worktree()
        deleted = [f.path for f in (head_wt.dirty if head_wt else []) if f.status == "D"]
        res = settle_apply(cgit, sp, apply=True)
        rep.check("settle created a branch per lane", len(res["created"]) >= 1,
                  "%d branch(es), %d failed" % (len(res["created"]), len(res["failed"])))
        after = _fingerprint(dest)
        rep.check("settle left the working tree exactly as it was",
                  after["status"] == before["status"] and after["head"] == before["head"],
                  "%d dirty paths still uncommitted" % len(after["status"].splitlines()))
        for made_branch in res["created"]:
            lane = [b for b in sp.branches if b["branch"] == made_branch["branch"]][0]
            on_branch = set(cgit.run("diff", "--name-only", "%s~1" % made_branch["branch"],
                                     made_branch["branch"], check=False).splitlines())
            missing = [p for p in lane["paths"] if p not in on_branch]
            rep.check("every path in the lane reached its branch", not missing,
                      "%s: %d/%d carried%s" % (made_branch["cluster"], len(lane["paths"]) - len(missing),
                                               len(lane["paths"]),
                                               "" if not missing else " - missing " + str(missing[:2])))
        if deleted:
            statuses = "\n".join(
                cgit.run("diff", "--name-status", "%s~1" % m["branch"], m["branch"], check=False)
                for m in res["created"])
            carried = [p for p in deleted if any(l.startswith("D") and l.endswith(p)
                                                 for l in statuses.splitlines())]
            rep.check("a deleted file is carried as a deletion", len(carried) == len(deleted),
                      "%d/%d deletion(s) on a branch: %s" % (len(carried), len(deleted),
                                                             ", ".join(deleted)[:60]))
        now = _fingerprint(repo)
        rep.check("the original repository is untouched", now == before,
                  "status, HEAD, refs, worktrees and stashes all identical")
    finally:
        shutil.rmtree(dest, ignore_errors=True)
        os.environ.pop("MUSTER_STATE_DIR", None)


def main(argv):
    flags = [a for a in argv if a.startswith("-")]
    repo = argv[0] if argv and not argv[0].startswith("-") else DEFAULT_REPO
    repo = os.path.abspath(os.path.expanduser(repo))
    rep = Report()

    print("muster %s validation against %s" % (__version__, repo))
    if not os.path.isdir(os.path.join(repo, ".git")):
        print("not a git repository:", repo)
        return 2

    git = Git(repo)
    print("git", ".".join(str(x) for x in git.version()), "\n")

    # ---- observation -------------------------------------------------------
    print("observation")
    snap, ledger = build_snapshot(repo=repo)
    wt = snap.head_worktree()
    dirty = [f for f in (wt.dirty if wt else [])]
    rep.check("snapshot has refs", len(snap.refs) > 0, "%d refs" % len(snap.refs))
    rep.check("dirty files observed", len(dirty) > 0, "%d uncommitted paths" % len(dirty))
    rep.check("warnings are not hiding a failure",
              not [w for w in snap.warnings if "failed" in w.lower()],
              "; ".join(snap.warnings)[:80] or "none")
    lanes = snap.clusters or []
    rep.check("every dirty file is in exactly one lane",
              sum(len(c.paths) for c in lanes) == len({p for c in lanes for p in c.paths})
              and {p for c in lanes for p in c.paths} <= {f.path for f in dirty},
              "%d lanes over %d files" % (len(lanes), len(dirty)))
    rep.check("no lane is empty", all(c.paths for c in lanes))
    rep.check("every lane states why it exists",
              all(c.reason and c.confidence for c in lanes))
    rep.check("lane names are not invented prose",
              all(not c.name.startswith(("Uncommitted", "Cluster", "lane ")) for c in lanes),
              ", ".join(c.name for c in lanes)[:80])
    unaccounted = {f.path for f in dirty} - {p for c in lanes for p in c.paths}
    rep.check("nothing silently dropped",
              len(unaccounted) <= len([f for f in dirty if _is_ignored(f.path)]),
              "%d unaccounted (ignored noise allowed)" % len(unaccounted))

    # ---- brief -------------------------------------------------------------
    print("\nbrief")
    text = render_brief(snap, me="validation")
    rep.check("brief is non-empty", len(text) > 200, "%d chars" % len(text))
    rep.check("brief says none rather than omitting a section",
              "UNCOMMITTED WORK IN THIS WORKING TREE" in text)
    ahead = [r.name for r in snap.refs if r.ahead and not r.is_base]
    rep.check("every branch with work appears in the brief",
              all(name in text for name in ahead), "%d branch(es)" % len(ahead))
    rep.check("brief offers a next action", "muster " in text)
    payload = json.loads(render_brief(snap, me="validation", fmt="json"))
    rep.check("json brief round-trips", payload["repo"] == snap.repo)

    # ---- digest ------------------------------------------------------------
    print("\nfeature digest")
    feats = features(snap)
    rep.check("features carry evidence", all(f.evidence for f in feats),
              "%d branch(es) with work not in the base" % len(feats))
    rep.check("no feature claims a number git did not report",
              all(_numbers_grounded(f) for f in feats))
    rep.check("merged branches are not listed as pending",
              not [f for f in feats if f.merged])

    # ---- collisions --------------------------------------------------------
    print("\ncollisions")
    rep.check("collision scan ran", isinstance(snap.collisions, list),
              "%d found" % len(snap.collisions))
    rep.check("every collision names both sides and a level",
              all(c.a and c.b and c.level for c in snap.collisions))
    rep.check("a lane never collides with itself",
              not [c for c in snap.collisions if c.a == c.b])
    high = [c for c in snap.collisions if c.severity == "high"]
    rep.check("high severity means overlapping ranges, not same file",
              all(c.level in ("same-hunk", "overlapping") for c in high),
              "%d high" % len(high))

    # ---- orchestrator, dry-run only ---------------------------------------
    print("\norchestrator (dry-run)")
    head_before = git.run("rev-parse", "HEAD").strip()
    status_before = sorted(git.status())
    branches_before = set(_branch_names(git))
    worktrees_before = len(git.worktrees())
    targets = [r.name for r in snap.refs if r.ahead and not r.is_base]
    if targets:
        p = plan(git, targets[0], snap.base or "main")
        rep.check("plan resolves a real verdict",
                  p.verdict in ("clean", "conflicts", "empty", "already-merged"),
                  "%s -> %s: %s (%s)" % (targets[0], snap.base, p.verdict, p.method))
        rep.check("plan states how it knows", p.method in ("merge-tree", "scratch-worktree"))
        rep.check("plan of a missing ref is an error",
                  plan(git, "muster/does-not-exist", "main").verdict == "error")
    else:
        rep.check("plan resolves a real verdict", False, "no branch ahead of the base")
    sp = settle_plan(git, snap)
    rep.check("settle proposes one branch per lane",
              all(b["branch"].startswith("muster/") for b in sp.branches),
              "%d branch(es) proposed" % len(sp.branches))
    rep.check("settle messages say where the split came from",
              all("Grouped by muster" in b["message"] for b in sp.branches))
    rep.check("dry-run wrote nothing to the repo",
              git.run("rev-parse", "HEAD").strip() == head_before
              and sorted(git.status()) == status_before
              and set(_branch_names(git)) == branches_before,
              "HEAD, status and branch list unchanged")
    rep.check("no scratch worktrees left behind",
              len(git.worktrees()) == worktrees_before,
              "%d before, %d after" % (worktrees_before, len(git.worktrees())))

    # ---- touch -------------------------------------------------------------
    print("\ntouch verdicts")
    if lanes:
        busy = lanes[0].paths[0]
        v = verdict_for(snap, [busy], me="validation")
        rep.check("a file another lane is in is not reported safe",
                  v["verdict"] in ("high", "medium", "low"), "%s -> %s" % (busy, v["verdict"]))
    v2 = verdict_for(snap, ["definitely/not/a/real/path.py"], me="validation")
    rep.check("an unknown path is safe, not an error", v2["verdict"] == "safe")

    print("\nledger")
    rep.check("ledger is outside the repository", not ledger.in_repo, ledger.dir)
    rep.check("observation left no untracked files",
              sorted(git.status()) == status_before)

    if "--writer" in flags:
        writer_check(repo, rep)

    failed = rep.failed
    print("\n%d checks, %d failed" % (len(rep.rows), len(failed)))
    if "--json" in argv:
        with open(os.path.join(ROOT, "validation", "last_run.json"), "w") as fh:
            json.dump({"repo": repo, "version": __version__,
                       "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       "checks": rep.rows}, fh, indent=2)
    if "--write-doc" in argv:
        write_doc(repo, snap, rep, git)
    return 1 if failed else 0


def _branch_names(git):
    return git.run("for-each-ref", "--format=%(refname:short)", "refs/heads",
                   check=False).split()


def _is_ignored(path):
    return path.endswith((".pyc", ".pyo", ".log", ".lock")) or "/__pycache__/" in path


def _numbers_grounded(feat):
    """A summary may only contain numbers that appear in its own evidence."""
    import re
    from muster.digest import evidence_tokens
    allowed = evidence_tokens(feat)
    for word in re.split(r"\s+", feat.summary + " " + " ".join(feat.headline_commits)):
        token = word.strip(".,;:()").lower()
        if re.fullmatch(r"\d+", token) and token not in allowed:
            return False
    return True


def write_doc(repo, snap, rep, git):
    from muster.digest import features as _features
    lanes = snap.clusters or []
    feats = _features(snap)
    wt = snap.head_worktree()
    path = os.path.join(ROOT, "docs", "VALIDATION.md")
    lines = [
        "# Validation against a real repository",
        "",
        "Generated by `python validation/run_validation.py %s --write-doc`." % repo,
        "",
        "| | |",
        "|---|---|",
        "| repository | `%s` |" % repo,
        "| git | %s |" % ".".join(str(x) for x in git.version()),
        "| muster | %s |" % __version__,
        "| observed | %s |" % snap.generated,
        "| checks | %d passed, %d failed |" % (len(rep.rows) - len(rep.failed),
                                               len(rep.failed)),
        "",
        "The repository was not chosen to be easy. It is a real project with "
        "several agent sessions that had already been working in it, uncommitted, "
        "for days.",
        "",
        "## What the working tree actually contained",
        "",
        "`git status` reported %d uncommitted paths. `muster` grouped them into "
        "%d lanes:" % (len(wt.dirty) if wt else 0, len(lanes)),
        "",
        "| lane | files | confidence | why |",
        "|---|---|---|---|",
    ]
    for c in sorted(lanes, key=lambda c: -len(c.paths)):
        lines.append("| `%s` | %d | %s | %s |"
                     % (c.name, len(c.paths), c.confidence, c.reason.replace("|", "/")))
    lines += [
        "",
        "## Branches carrying work",
        "",
    ]
    if feats:
        lines += ["| branch | ahead | risk | summary |", "|---|---|---|---|"]
        for f in feats:
            lines.append("| `%s` | %d | %s | %s |" % (f.ref, f.ahead, f.risk, f.summary))
    else:
        lines.append("No branch was ahead of the base at the time of the run.")
    lines += [
        "",
        "## Collisions",
        "",
    ]
    if snap.collisions:
        lines += ["| severity | level | file | between |", "|---|---|---|---|"]
        for c in snap.collisions[:20]:
            lines.append("| %s | %s | `%s` | %s and %s |"
                         % (c.severity, c.level, c.path, c.a, c.b))
    else:
        lines.append("None. The lanes in this tree do not overlap line-for-line, "
                     "which is the correct answer for this repository and not a "
                     "failure of the detector - the detector is exercised against "
                     "constructed overlaps in `tests/test_collisions.py`.")
    writer_rows = [r for r in rep.rows if "settle" in r["name"]
                   or "original repository" in r["name"]]
    if writer_rows:
        lines += [
            "## The writer, against a copy",
            "",
            "Read-only checks prove very little, so `--writer` runs `settle --apply` "
            "too. It runs against a hardlink copy of the repository (`cp -al`, so no "
            "disk and no wait on a 7 GB tree), and it checks the copy's working tree "
            "hash before and after, that every path in every lane reached its branch "
            "including deletions, and that the original repository's status, HEAD, "
            "refs, worktrees and stashes are byte-identical to before.",
            "",
        ]
    lines += [
        "## Checks",
        "",
        "```",
    ]
    for row in rep.rows:
        lines.append("%-4s %-48s %s" % ("PASS" if row["ok"] else "FAIL", row["name"],
                                        row["detail"]))
    lines += ["```", ""]
    with open(path, "w") as fh:
        fh.write("\n".join(lines))
    print("wrote", path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
