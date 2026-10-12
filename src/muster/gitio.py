
"""Thin, dependency-free wrapper around the git CLI.

Every call is a plain subprocess with argument lists (no shell). Failures raise
GitError with captured stderr so callers report a real reason instead of
returning an empty list. Silent-empty is the failure mode this module is written
against: a git command that exits non-zero must never look like "no branches".
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass


class GitError(RuntimeError):
    def __init__(self, args, code, stderr):
        self.git_args = list(args)
        self.code = code
        self.stderr = stderr
        super().__init__(
            "git %s failed (%s): %s" % (" ".join(args), code, (stderr or "").strip()[:400])
        )


_HUNK_RX = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_hunks(diff_text):
    """Line ranges touched on the '+' side of a unified diff."""
    ranges = []
    for line in diff_text.splitlines():
        m = _HUNK_RX.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2)) if m.group(2) is not None else 1
        ranges.append([start, start + max(count, 1) - 1])
    return ranges


def identity():
    """`git -c` flags giving muster's own commits an author.

    A machine with no `user.name` configured must still be able to merge, settle
    and sync. These commits are bookkeeping muster performs on the user's behalf;
    git refusing to guess an email is not a reason to lose the work, and blaming
    the user's identity for it would be wrong too. Override with
    MUSTER_COMMITTER_NAME / MUSTER_COMMITTER_EMAIL.
    """
    name = os.environ.get("MUSTER_COMMITTER_NAME") or "muster"
    mail = os.environ.get("MUSTER_COMMITTER_EMAIL") or "muster@localhost"
    return ("-c", "user.name=" + name, "-c", "user.email=" + mail)


@dataclass
class Git:
    repo: str
    env: dict | None = None

    # ---- plumbing --------------------------------------------------------

    def _env(self):
        e = dict(os.environ)
        # A read-only scan must never block on a pager, editor or prompt.
        e["GIT_TERMINAL_PROMPT"] = "0"
        e["GIT_MERGE_AUTOEDIT"] = "no"
        e["GIT_PAGER"] = "cat"
        for k in ("GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_DIR", "GIT_NAMESPACE"):
            e.pop(k, None)
        if self.env:
            e.update(self.env)
        return e

    def run(self, *args, stdin=None, check=True, cwd=None, combine=False):
        """Run git and return stdout.

        `combine=True` folds stderr into stdout. Git writes the interesting part
        of every write operation - merge results, push rejections, most errors -
        to stderr, so a write path that reads only stdout can watch a failed
        merge and report that nothing happened.
        """
        cmd = ["git", "-c", "core.quotepath=false", *args]
        proc = subprocess.run(
            cmd, cwd=cwd or self.repo, input=stdin, env=self._env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if combine else subprocess.PIPE,
        )
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace") if proc.stderr else out
        if check and proc.returncode != 0:
            raise GitError(args, proc.returncode, err)
        return out

    # ---- discovery -------------------------------------------------------

    @classmethod
    def detect(cls, start=None):
        start = os.path.abspath(start or os.getcwd())
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=start,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if out.returncode != 0:
            raise GitError(
                ("rev-parse", "--show-toplevel"), out.returncode,
                out.stderr.decode("utf-8", "replace") or ("not a git repository: " + start),
            )
        return cls(repo=out.stdout.decode().strip())

    def version(self):
        tok = self.run("--version").split()[2]
        parts = [int(p) for p in tok.split("-")[0].split(".")[:3]]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts)

    def toplevel(self):
        return self.run("rev-parse", "--show-toplevel").strip()

    def common_dir(self):
        d = self.run("rev-parse", "--git-common-dir").strip()
        return d if os.path.isabs(d) else os.path.normpath(os.path.join(self.repo, d))

    def head_ref(self):
        return self.run("symbolic-ref", "--short", "-q", "HEAD", check=False).strip() or None

    def head_sha(self):
        return self.run("rev-parse", "--verify", "-q", "HEAD", check=False).strip() or None

    def _ref_exists(self, ref):
        for cand in ("refs/heads/" + ref, "refs/remotes/origin/" + ref, ref):
            if self.run("rev-parse", "--verify", "-q", cand, check=False).strip():
                return True
        return False

    def resolve(self, ref):
        return self.run("rev-parse", "--verify", "-q", ref + "^{commit}").strip()

    def default_branch(self):
        """Best-effort base branch, without touching the network."""
        for cand in self._default_candidates():
            if cand and self._ref_exists(cand):
                return cand
        out = self.run("for-each-ref", "--format=%(refname:short)",
                       "--sort=-committerdate", "refs/heads", check=False).split()
        if out:
            return out[0]
        raise GitError(("default-branch",), 1,
                       "no local branches and no origin/HEAD; pass --base explicitly")

    def _default_candidates(self):
        sym = self.run("symbolic-ref", "-q", "refs/remotes/origin/HEAD", check=False).strip()
        if sym:
            short = sym.replace("refs/remotes/", "", 1)
            yield short
            yield short.split("/", 1)[-1]
        cfg = self.run("config", "--get", "muster.base", check=False).strip()
        if cfg:
            yield cfg
        for name in ("main", "master", "develop", "trunk"):
            yield name

    def refs(self, include_remotes=True):
        """Yield (short_name, kind, sha, committer_iso, author, subject)."""
        fmt = "%(refname:short)\x1f%(objectname)\x1f%(committerdate:iso-strict)\x1f%(authorname)\x1f%(subject)"
        specs = ["refs/heads"] + (["refs/remotes"] if include_remotes else [])
        seen = set()
        for spec in specs:
            out = self.run("for-each-ref", "--format=" + fmt, "--sort=-committerdate",
                           spec, check=False)
            for line in out.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\x1f")
                while len(parts) < 5:
                    parts.append("")
                short, sha, date, author, subject = parts[:5]
                if short.endswith("/HEAD"):
                    continue
                kind = "branch" if spec == "refs/heads" else "remote"
                dedupe = short.split("/", 1)[-1] if kind == "remote" else short
                key = (dedupe, sha)
                if key in seen:
                    continue
                seen.add(key)
                yield short, kind, sha, date, author, subject

    def log(self, rev, limit=200):
        fmt = "%H\x1f%an\x1f%ae\x1f%aI\x1f%s\x1f%b\x1e"
        out = self.run("log", "--format=" + fmt, "--max-count=%d" % limit, rev, check=False)
        recs = []
        for chunk in out.split("\x1e"):
            chunk = chunk.strip("\n")
            if not chunk.strip():
                continue
            parts = chunk.split("\x1f")
            while len(parts) < 6:
                parts.append("")
            recs.append({"sha": parts[0], "author": parts[1], "email": parts[2],
                         "date": parts[3], "subject": parts[4], "body": parts[5]})
        return recs

    def merge_base(self, a, b):
        return self.run("merge-base", a, b).strip()

    def ahead_behind(self, base, head):
        out = self.run("rev-list", "--left-right", "--count", "%s...%s" % (base, head),
                       check=False).split()
        if len(out) != 2:
            return (0, 0)
        try:
            return (int(out[1]), int(out[0]))  # (ahead of base, behind base)
        except ValueError:
            return (0, 0)

    def name_status(self, base, head, rename=True):
        """Files changed between merge-base(base, head) and head."""
        mb = self.merge_base(base, head)
        args = ["diff", "--name-status", "-M" if rename else "--no-renames", mb, head]
        out = self.run(*args, check=False)
        changes = []
        for line in out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            status = parts[0]
            if status.startswith(("R", "C")) and len(parts) >= 3:
                changes.append((status[0], parts[1], parts[2]))
            elif len(parts) >= 2:
                changes.append((status[0], parts[1], None))
        return changes

    def numstat(self, base, head):
        mb = self.merge_base(base, head)
        out = self.run("diff", "--numstat", mb, head, check=False)
        res = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            try:
                add, dele = int(parts[0]), int(parts[1])
            except ValueError:
                add, dele = -1, -1  # binary
            res[parts[-1]] = (add, dele)
        return res

    def status(self, untracked=True, ignored=False):
        """[(xy, path, orig_path|None)] using -z so odd filenames survive."""
        args = ["status", "--porcelain=v1", "-z",
                "--untracked-files=all" if untracked else "--untracked-files=no"]
        if ignored:
            args.append("--ignored")
        out = self.run(*args)
        toks = out.split("\0")
        res, i = [], 0
        while i < len(toks):
            tok = toks[i]
            if not tok:
                i += 1
                continue
            xy, path = tok[:2], tok[3:]
            orig = None
            if ("R" in xy or "C" in xy) and i + 1 < len(toks) and toks[i + 1]:
                orig = toks[i + 1]
                i += 1
            res.append((xy, path, orig))
            i += 1
        return res

    def worktrees(self):
        out = self.run("worktree", "list", "--porcelain", check=False)
        res, cur = [], {}
        for line in out.splitlines():
            if not line.strip():
                if cur:
                    res.append(cur)
                    cur = {}
                continue
            if line.startswith("worktree "):
                cur["path"] = line[len("worktree "):]
            elif line.startswith("HEAD "):
                cur["head"] = line[len("HEAD "):]
            elif line.startswith("branch "):
                cur["branch"] = line[len("branch "):].replace("refs/heads/", "", 1)
            elif line == "bare":
                cur["bare"] = True
            elif line == "detached":
                cur["detached"] = True
        if cur:
            res.append(cur)
        return res

    def new_roots(self):
        """Directories that are entirely untracked, e.g. `new-feature/`.

        `status --untracked-files=normal` collapses a brand-new directory into one
        entry. That collapse is the strongest available signal that everything
        inside arrived as a single piece of work, so it is worth a second call.
        """
        out = self.run("status", "--porcelain=v1", "-z", "--untracked-files=normal")
        roots = []
        for tok in out.split("\0"):
            if not tok:
                continue
            if tok[:2] == "??" and tok[3:].endswith("/"):
                roots.append(tok[3:])
        return roots

    def stash_list(self):
        return [l for l in self.run("stash", "list", check=False).splitlines() if l.strip()]

    def ref_hunks(self, base, head, path):
        return _parse_hunks(self.run("diff", "--unified=0", self.merge_base(base, head),
                                     head, "--", path, check=False))

    def worktree_hunks(self, path, staged=False):
        args = ["diff", "--unified=0"] + (["--cached"] if staged else []) + ["--", path]
        return _parse_hunks(self.run(*args, check=False))

    def show(self, ref, path):
        return self.run("show", "%s:%s" % (ref, path), check=False) or None

    # ---- writing (only reached by explicit mutating verbs) ----------------

    def worktree_add(self, path, ref, detach=True):
        args = ["worktree", "add"] + (["--detach"] if detach else []) + [path, ref]
        self.run(*args)

    def worktree_remove(self, path, force=True):
        args = ["worktree", "remove"] + (["--force"] if force else []) + [path]
        self.run(*args, check=False)
        self.run("worktree", "prune", check=False)

    def merge_tree(self, ours, theirs):
        """Fast conflict probe via `git merge-tree --write-tree` (git >= 2.38).

        Returns (supported, clean, conflicted_paths, tree_oid). Callers must fall
        back to a scratch-worktree merge when supported is False: pre-2.38 git has
        a merge-tree with a completely different, unparseable-for-this-purpose
        output, so it is treated as unsupported rather than misread.
        """
        if self.version() < (2, 38, 0):
            return (False, False, [], None)
        out = self.run("merge-tree", "--write-tree", "--name-only", "--no-messages",
                       ours, theirs, check=False)
        lines = [l for l in out.splitlines() if l.strip()]
        if not lines or len(lines[0]) < 8:
            return (False, False, [], None)
        conflicted = [l.strip() for l in lines[1:] if l.strip()]
        return (True, not conflicted, conflicted, lines[0])
