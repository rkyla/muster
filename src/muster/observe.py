
"""Build a snapshot: everything the repo looks like right now, across sessions.

Two things drive the design:

* Nothing here needs the agents to cooperate. Branches, worktrees and the dirty
  working tree are observed from git. Declared sessions enrich the picture; they
  are not required for it to be useful.
* An empty result must look empty, not successful. Every stage appends to
  `warnings` when it finds nothing or fails partially, so a caller can tell
  "no other work" from "could not look".
"""

from __future__ import annotations

import fnmatch
import os
import re
import time

from .gitio import Git, GitError
from .model import (Claim, Cluster, Collision, FileChange, RefState, Session,
                    Snapshot, WorktreeState, now_iso)

# Directories that are almost never someone's feature.
NOISE_DIRS = (".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
              ".ruff_cache", ".mypy_cache", "dist", "build", ".next", ".muster")

DEFAULT_MTIME_WINDOW = 45 * 60  # minutes of edit-time proximity that suggests one task


def is_noise(path):
    parts = path.split("/")
    for seg in parts[:-1]:
        if seg in NOISE_DIRS or seg.startswith(".") and seg not in (".github",):
            return True
    base = parts[-1]
    return base in (".DS_Store", "Thumbs.db") or base.endswith((".pyc", ".pyo", ".log"))


def _mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


_touch_cache = {}


def _last_touch(sub: Git, path, cap=40):
    """Epoch of the most recent commit touching `path`. Bounded and cached."""
    key = (sub.repo, path)
    if key in _touch_cache:
        return _touch_cache[key]
    if len(_touch_cache) >= cap:
        return 0.0
    out = sub.run("log", "-1", "--format=%at", "--", path, check=False).strip()
    try:
        val = float(out)
    except ValueError:
        val = 0.0
    _touch_cache[key] = val
    return val


def _count_lines(abs_path, cap=2_000_000):
    """Line count for an untracked file, or -1 when it is binary or unreadable.

    Counting newlines in an .mp4 produced "+272 lines" on a real repo and made a
    media dump look like a code change. Binary is detected, not guessed.
    """
    try:
        size = os.path.getsize(abs_path)
        if size > cap:
            return -1
        with open(abs_path, "rb") as fh:
            head = fh.read(8192)
            if b"\0" in head:
                return -1
            lines = 1 + head.count(b"\n")
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                if b"\0" in chunk:
                    return -1
                lines += chunk.count(b"\n")
        return lines
    except OSError:
        return -1


# --------------------------------------------------------------------------- #
# refs
# --------------------------------------------------------------------------- #

def collect_refs(git: Git, base: str, head_branch, warnings):
    base_sha = git.resolve(base)
    head_sha = git.head_sha()
    raw = list(git.refs(include_remotes=True))
    if not raw:
        warnings.append("no branches found under refs/heads or refs/remotes")

    # A remote ref that points at the same commit as a local branch is the same
    # work seen twice; keep the local one and remember the remote name.
    by_local = {}
    for short, kind, sha, date, author, subject in raw:
        if kind == "branch":
            by_local.setdefault(sha, []).append(short)

    out = []
    for short, kind, sha, date, author, subject in raw:
        if kind == "remote":
            local_dupes = by_local.get(sha, [])
            bare = short.split("/", 1)[-1] if short.startswith("origin/") else short
            if any(d == bare for d in local_dupes):
                continue  # already represented by the local branch
        try:
            mb = git.merge_base(base, sha)
        except GitError as exc:
            warnings.append("merge-base failed for %s: %s" % (short, exc))
            continue
        ahead, behind = git.ahead_behind(base, sha)
        is_base = (sha == base_sha)
        ref = RefState(
            name=short, kind=kind, sha=sha, committer_date=date, author=author,
            subject=subject, base=base, merge_base=mb, ahead=ahead, behind=behind,
            is_base=is_base, is_head=bool(head_sha and sha == head_sha),
            merged_into_base=(mb == sha and sha != base_sha),
        )
        if ahead or (not is_base and mb != sha):
            ref.commits = git.log(sha, limit=60)
            ref.commits = _since_merge_base(ref.commits, mb)
            ref.files = _ref_files(git, mb, sha)
        out.append(ref)

    out.sort(key=lambda r: (not r.is_head, _epoch_of(r.committer_date)), reverse=False)
    return out


def _since_merge_base(commits, merge_base_sha):
    """Trim the shared history: only commits the ref actually adds."""
    keep = []
    for c in commits:
        if c["sha"] == merge_base_sha:
            break
        keep.append(c)
    return keep


def _ref_files(git: Git, mb, sha, max_files=400):
    changes = git.name_status(mb, sha)
    numstat = git.numstat(mb, sha)
    files = []
    for status, path, old in changes[:max_files]:
        add, dele = numstat.get(path, (-1, -1))
        if add == -1 and old in numstat:
            add, dele = numstat[old]
        files.append(FileChange(path=path, status=status, old_path=old,
                                lines_added=add, lines_deleted=dele))
    return files


# --------------------------------------------------------------------------- #
# worktrees
# --------------------------------------------------------------------------- #

def collect_worktrees(git: Git, warnings, untracked=True):
    main = git.toplevel()
    entries = git.worktrees()
    if not entries:
        warnings.append("git worktree list returned nothing")
    out = []
    for e in entries:
        path = e.get("path", "")
        if e.get("bare"):
            continue
        wt = WorktreeState(path=path, branch=e.get("branch"), head=e.get("head", ""),
                           detached=bool(e.get("detached")), is_main=(os.path.abspath(path) == main))
        try:
            sub = Git(repo=path)
            out.append(_fill_dirty(sub, wt, untracked))
        except GitError as exc:
            warnings.append("could not read worktree %s: %s" % (path, exc))
            out.append(wt)
    return out


def _fill_dirty(sub: Git, wt: WorktreeState, untracked=True):
    try:
        tracked_add, tracked_del = _worktree_numstat(sub)
    except GitError:
        tracked_add, tracked_del = {}, {}
    changes = []
    roots = sub.new_roots() if untracked else []
    wt.new_roots = roots
    for xy, path, orig in sub.status(untracked=untracked):
        if xy.startswith("!!"):
            continue
        code = xy[1] if xy[1] not in " " else xy[0]
        if code == "?":
            if is_noise(path):
                continue
            add = _count_lines(os.path.join(sub.repo, path))
            dele = 0
        else:
            add = tracked_add.get(path, -1)
            dele = tracked_del.get(path, -1)
        ts = _mtime(os.path.join(sub.repo, path))
        if not ts:
            # Deleted or unreadable: the file has no mtime, but git knows when it
            # was last touched, which is the next best thing for lane grouping.
            ts = _last_touch(sub, path)
        fc = FileChange(path=path, status=code, old_path=orig,
                        lines_added=add, lines_deleted=dele, mtime=ts)
        changes.append(fc)
    wt.dirty = changes
    return wt


def _worktree_numstat(sub: Git):
    """Added/deleted lines for the working tree vs HEAD (staged and unstaged)."""
    adds, dels = {}, {}
    for line in sub.run("diff", "--numstat", "HEAD", check=False).splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            adds[parts[-1]], dels[parts[-1]] = int(parts[0]), int(parts[1])
        except ValueError:
            adds[parts[-1]], dels[parts[-1]] = -1, -1  # binary
    return adds, dels


# --------------------------------------------------------------------------- #
# clustering the dirty tree
# --------------------------------------------------------------------------- #

def _feature_key(path):
    """Directory-ish identity of a path, used for affinity."""
    parts = path.split("/")
    if len(parts) == 1:
        return parts[0]
    # drop the filename, keep up to the last two directories
    d = parts[:-1]
    return "/".join(d[-2:]) if len(d) >= 2 else d[0]


def _top_area(path):
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "."


def _leaf_dir(path):
    return os.path.dirname(path) or "."


_NAME_STOP = {
    "json", "yaml", "yml", "test", "tests", "testpy", "spec", "src", "app", "work",
    "main", "index", "readme", "data", "report", "reports", "run", "root", "tmp",
    "temp", "new", "old", "bak", "copy", "final", "notes", "config", "example",
}


def _name_tokens(label):
    """Distinctive words in a file or directory name, for name affinity only."""
    words = [w for w in re.split(r"[^A-Za-z]+", str(label)) if len(w) >= 4]
    return {w.lower() for w in words if w.lower() not in _NAME_STOP}


def cluster_changes(dirty, window=DEFAULT_MTIME_WINDOW, max_files=1200, new_roots=()):
    """Group dirty files into lanes: sets of files one session touched together.

    Rules, in order, each recorded on the cluster it produced:

    1. A directory that is itself entirely new is one lane. Git reports a new
       directory as a single untracked entry, which is the strongest available
       signal that everything under it came from one piece of work.
    2. Otherwise, order files by last touch and cut wherever the gap exceeds
       `window`. Time is the primary signal because a lane is a session's sitting.
    3. A block wider than `max_spread` is cut again at its largest internal gap, so
       one long day of work does not swallow unrelated lanes.
    4. A file with no usable timestamp (deleted, or unreadable) attaches to the lane
       that shares its directory, and is marked low confidence if it cannot.

    Directory affinity is deliberately NOT a merge rule on its own: `video_editor/`
    holding two unrelated lanes three days apart is exactly the false positive that
    makes a brief useless.
    """
    files = [f for f in dirty if not is_noise(f.path)][:max_files]
    if not files:
        return []
    roots = sorted({r.rstrip("/") + "/" for r in new_roots}, key=len, reverse=True)

    # A deleted file has no mtime, and git's last-touch time for it is when it was
    # written to HEAD, not when it was deleted. Treat it as undated and place it by
    # directory instead of pretending the timestamp means something.
    undated = [f for f in files if f.status == "D" or not f.mtime]
    dated = [f for f in files if f not in undated]

    by_root = {}
    for f in dated:
        root = next((r for r in roots if f.path.startswith(r)), None)
        if root:
            by_root.setdefault(root, []).append(f)

    clusters = []

    # Units are new-directory groups plus loose files. Each unit is emitted once,
    # by the sweep below - pre-emitting root groups here produced the same 89 files
    # twice, as a directory lane and again as a time lane. Sweeping units rather than
    # files keeps a new directory and the tracked files edited alongside it in one
    # lane, which is what a single session actually produces.
    placed = {f.path for members in by_root.values() for f in members}
    units = [(_Unit(members, root.rstrip("/"), "new-directory"))
             for root, members in by_root.items()]
    units += [_Unit([f], f.path, "edit-time") for f in dated if f.path not in placed]
    units.sort(key=lambda u: u.start)

    blocks = []
    for u in units:
        if blocks and (u.start - blocks[-1].end) <= window:
            blocks[-1].extend(u)
        else:
            blocks.append(u)

    # rule 3: cut over-wide blocks at their largest internal gap
    max_spread = max(window * 4, 4 * 3600)
    for block in blocks:
        for piece in _split_unit(block, max_spread):
            members = list(piece.members)
            members.sort(key=lambda f: f.mtime or 0)
            # A new directory keeps its own name even with one file in it: the
            # directory is the unit of work, and a later rule may add to it.
            label = (piece.label if len(piece) > 1 or piece.kind == "new-directory"
                     else members[0].path)
            rule = ("new-directory" if piece.pristine and piece.kind == "new-directory"
                    else "edit-time")
            clusters.append((label, members, rule))

    # rule 4: attach undated files by directory
    for f in undated:
        home = next((c for c in clusters
                     if any(_leaf_dir(g.path) == _leaf_dir(f.path) for g in c[1])), None)
        if home:
            home[1].append(f)
        else:
            clusters.append((f.path, [f], "undated"))

    # rule 5: a loose file named after a new directory is that lane's state file.
    # `videoEditor` had `.brag_run_root.json` sitting alone 12 days from the
    # `brag-2026-10-08-110237/` lane it configures. Only a distinctive shared word
    # counts, and only when exactly one lane claims it, so this cannot weld two
    # lanes together the way directory affinity did.
    root_labels = [c for c in clusters if c[2] == "new-directory"]
    for c in [c for c in clusters if c[2] == "edit-time" and len(c[1]) == 1]:
        f = c[1][0]
        mine = _name_tokens(os.path.splitext(os.path.basename(f.path))[0])
        if not mine:
            continue
        hits = [rc for rc in root_labels if rc is not c and rc[1] is not c[1]
                and _name_tokens(rc[0]) & mine]
        if len(hits) == 1:
            hits[0][1].append(f)
            clusters.remove(c)

    out = []
    for label, members, rule in clusters:
        members.sort(key=lambda f: f.mtime or 0)
        # A deleted file's timestamp is when HEAD last saw it, not when it was
        # removed, so it must not define the lane's time span.
        mtimes = [f.mtime for f in members if f.mtime and f.status != "D"]
        spread = (max(mtimes) - min(mtimes)) if len(mtimes) > 1 else 0
        dirs = sorted({_leaf_dir(f.path) for f in members})
        if rule == "new-directory":
            conf = "high"
            reason = "everything under %s/ is new, so it arrived as one piece of work" % label
        elif rule == "undated":
            conf = "low"
            reason = "no timestamp available for this file"
        elif rule == "name-affinity":
            conf = "medium"
            reason = "named after %s/, which is one new piece of work" % label
        elif len(members) == 1:
            conf = "low"
            reason = "only file touched in this window"
        else:
            conf = "medium"
            reason = ("touched together within %dm across %s"
                      % (max(int(spread / 60) + 1, 1), ", ".join(dirs[:3])))
        # Name after a wholly new directory when the lane contains one, even if
        # the lane was formed by time: `brag-2026-10-08-110237` beats
        # `.brag_run_root.json+1 more` as something a human can act on.
        home_root = None
        if rule != "new-directory":
            counts = {}
            for r in roots:
                counts[r] = sum(1 for f in members if f.path.startswith(r))
            if counts:
                home_root = max(counts, key=lambda r: (counts[r], -len(r)))
                if counts[home_root] == 0:
                    home_root = None
        out.append(Cluster(
            name=_cluster_name(members, label=label, rule=rule, root=home_root),
            paths=[f.path for f in members],
            reason=reason, confidence=conf,
            first_mtime=min(mtimes) if mtimes else 0.0,
            last_mtime=max(mtimes) if mtimes else 0.0,
            added=sum(f.lines_added for f in members if f.lines_added > 0),
            deleted=sum(f.lines_deleted for f in members if f.lines_deleted > 0),
            evidence=["%s %s" % (f.status, f.path) for f in members[:12]],
        ))
    out.sort(key=lambda c: (-len(c.paths), -c.last_mtime))
    seen = {}
    for c in out:
        seen[c.name] = seen.get(c.name, 0) + 1
        if seen[c.name] > 1:
            c.name = "%s (%d)" % (c.name, seen[c.name])
    return out


class _Unit:
    """A sortable chunk of work: a new directory, or one loose file."""

    def __init__(self, members, label, kind, pristine=True):
        self.members = list(members)
        self.label = label
        self.kind = kind
        # pristine: still exactly one new directory, never merged with anything.
        self.pristine = pristine

    @property
    def start(self):
        ts = [f.mtime for f in self.members if f.mtime]
        return min(ts) if ts else 0.0

    @property
    def end(self):
        ts = [f.mtime for f in self.members if f.mtime]
        return max(ts) if ts else 0.0

    def extend(self, other):
        self.members.extend(other.members)
        self.pristine = False
        if other.kind == "new-directory":
            self.kind = "mixed"

    def __len__(self):
        return len(self.members)


def _split_unit(unit, max_spread):
    """Cut an over-wide unit at its largest internal gap, recursively."""
    members = sorted(unit.members, key=lambda f: f.mtime or 0)
    if len(members) <= 1 or (members[-1].mtime - members[0].mtime) <= max_spread:
        return [unit]
    gaps = [(members[i + 1].mtime - members[i].mtime, i) for i in range(len(members) - 1)]
    _gap, idx = max(gaps, key=lambda g: g[0])
    left = _Unit(members[:idx + 1], unit.label, unit.kind, pristine=unit.pristine)
    right = _Unit(members[idx + 1:], unit.label, unit.kind, pristine=unit.pristine)
    out = []
    out.extend(_split_unit(left, max_spread))
    out.extend(_split_unit(right, max_spread))
    return out


def _cluster_name(members, label=None, rule=None, root=None):
    """Name a cluster from its own contents. Never invented prose."""
    if rule == "new-directory" and label:
        return os.path.basename(label.rstrip("/")) or label
    if root:
        # A brand-new directory in the lane is the most specific handle git gives.
        return (os.path.basename(root.rstrip("/")) or root)[:48]
    docs = [f for f in members if f.path.endswith((".md", ".rst"))
            and os.path.basename(f.path) not in ("README.md", "AGENTS.md", "CLAUDE.md")]
    if docs:
        return os.path.splitext(os.path.basename(docs[0].path))[0][:48]
    if len(members) == 1:
        return os.path.basename(members[0].path)[:48]
    dirs = sorted({_leaf_dir(f.path) for f in members})
    if len(dirs) == 1 and dirs[0] not in (".", ""):
        return (os.path.basename(dirs[0]) or dirs[0])[:48]
    return "%s+%d more" % (os.path.basename(members[0].path)[:32], len(members) - 1)


# --------------------------------------------------------------------------- #
# attribution
# --------------------------------------------------------------------------- #

def path_matches(declared, actual):
    """A claim over `src/` covers `src/a/b.py`; a glob works too."""
    d = declared.rstrip("/")
    if not d:
        return False
    if actual == d or actual.startswith(d + "/"):
        return True
    if any(ch in d for ch in "*?["):
        return fnmatch.fnmatch(actual, declared) or fnmatch.fnmatch(actual, d + "/*")
    return False


def attribute(dirty, sessions):
    """Map path -> session id using declared scopes. Later claims win on ties."""
    owner = {}
    for s in sorted(sessions, key=lambda s: s.updated or ""):
        if s.status == "done":
            continue
        for declared in s.paths:
            for f in dirty:
                if path_matches(declared, f.path):
                    owner[f.path] = s.id
    return owner


# --------------------------------------------------------------------------- #
# collisions
# --------------------------------------------------------------------------- #

def _overlap(a_hunks, b_hunks, tolerance=3):
    """Return (same_hunk, overlapping) for two lists of [start, end] ranges.

    `same_hunk` means the two sides rewrite lines in common. `overlapping` also
    covers ranges that stop within `tolerance` lines of each other: git will often
    merge those cleanly today, but they are the edits that turn into a conflict the
    moment either side grows by a line.
    """
    same = overlap = False
    for a in a_hunks:
        for b in b_hunks:
            lo, hi = max(a[0], b[0]), min(a[1], b[1])
            if hi - lo >= 0:
                overlap = True
                if hi - lo >= 2:
                    same = True
            elif abs(a[0] - b[1]) <= tolerance or abs(b[0] - a[1]) <= tolerance:
                overlap = True
    return same, overlap


def find_collisions(snap: Snapshot, me=None, max_paths=250):
    """Where does one actor's work touch another's?

    Compares every non-base ref against the working tree and against every other
    ref, plus declared session scopes against the working tree.
    """
    collisions = []
    wt = snap.head_worktree()
    dirty = {}
    if wt:
        for f in wt.dirty:
            if not is_noise(f.path):
                dirty[f.path] = f

    others = [r for r in snap.refs if not r.is_base and (r.ahead or r.files)]
    if len(others) > 24:
        snap.warnings.append("%d non-base refs; collision scan capped at 24" % len(others))
        others = others[:24]

    # ref vs working tree. HEAD's own ref is skipped: the working tree is measured
    # against HEAD, so every overlap there is this session's uncommitted delta, not
    # a clash with somebody else.
    for ref in [r for r in others if not r.is_head]:
        ref_files = {f.path: f for f in ref.files}
        for path in sorted(set(ref_files) & set(dirty))[:max_paths]:
            a, b = ref_files[path], dirty[path]
            a_h = _ref_hunks_cached(snap, ref, path)
            b_h = _wt_hunks(snap, path)
            same, over = _overlap(a_h, b_h)
            if same or over:
                level = "same-hunk" if same else "overlapping"
                sev = "high" if same else "medium"
            elif a.status == "D" or b.status == "D":
                level, sev = "rename", "high"
            else:
                level, sev = "same-file", "low"
            collisions.append(Collision(
                path=path, a=ref.name, b="working-tree", level=level, severity=sev,
                a_hunks=a_h[:8], b_hunks=b_h[:8],
                note=_note(level, ref.name, "your working tree", a_h, b_h),
            ))

    # ref vs ref (integration risk between lanes)
    for i, r1 in enumerate(others):
        for r2 in others[i + 1:]:
            shared = {f.path for f in r1.files} & {f.path for f in r2.files}
            for path in sorted(shared)[:40]:
                a_h = _ref_hunks_cached(snap, r1, path)
                b_h = _ref_hunks_cached(snap, r2, path)
                same, over = _overlap(a_h, b_h)
                level = "same-hunk" if same else ("overlapping" if over else "same-file")
                collisions.append(Collision(
                    path=path, a=r1.name, b=r2.name, level=level,
                    severity={"same-hunk": "high", "overlapping": "medium", "same-file": "low"}[level],
                    a_hunks=a_h[:8], b_hunks=b_h[:8],
                    note=_note(level, r1.name, r2.name, a_h, b_h),
                ))

    # lane vs lane inside the working tree: two clusters sharing a file must not
    # be committed together, and one of them is about to be surprised.
    for i, c1 in enumerate(snap.clusters):
        for c2 in snap.clusters[i + 1:]:
            shared = set(c1.paths) & set(c2.paths)
            for path in sorted(shared)[:20]:
                collisions.append(Collision(
                    path=path, a="lane:" + c1.name, b="lane:" + c2.name,
                    level="same-file", severity="high",
                    note="two uncommitted lanes both contain this file; settle would put it "
                         "in the first one only",
                ))

    # declared session scopes vs the working tree. Inferred lanes are excluded:
    # they were derived from this same dirty tree, so they would "collide" with
    # themselves on every file and bury the real warnings.
    wt_paths = set(dirty)
    for s in snap.sessions:
        if s.status == "done" or not s.paths or s.source.startswith("inferred"):
            continue
        hits = sorted({p for p in wt_paths for d in s.paths if path_matches(d, p)})
        for p in hits[:40]:
            if me and s.id == me:
                continue
            collisions.append(Collision(
                path=p, a=s.id, b="working-tree", level="same-file", severity="medium",
                note="%s declared scope %s which covers this file" % (s.id, _scope_for(s, p)),
            ))

    # declared scope vs declared scope: two sessions that said they own the same
    # place, before either of them has written anything
    live = [s for s in snap.sessions if s.status != "done" and s.paths
            and not s.source.startswith("inferred")]
    for i, s1 in enumerate(live):
        for s2 in live[i + 1:]:
            shared = sorted({a for a in s1.paths for b in s2.paths
                             if path_matches(a, b) or path_matches(b, a)})
            for scope in shared[:10]:
                collisions.append(Collision(
                    path=scope, a=s1.id, b=s2.id, level="same-file", severity="high",
                    note="both sessions declared this scope: %s / %s"
                         % (s1.intent or "no intent", s2.intent or "no intent"),
                ))

    order = {"high": 0, "medium": 1, "low": 2}
    collisions.sort(key=lambda c: (order.get(c.severity, 3), c.path))
    return collisions


_ref_hunk_cache = {}


def _ref_hunks_cached(snap, ref, path):
    key = (snap.repo, ref.name, ref.sha, path)
    if key not in _ref_hunk_cache:
        try:
            _ref_hunk_cache[key] = Git(snap.repo).ref_hunks(ref.base, ref.sha, path)
        except GitError:
            _ref_hunk_cache[key] = []
    return _ref_hunk_cache[key]


def _wt_hunks(snap, path):
    try:
        return Git(snap.repo).worktree_hunks(path)
    except GitError:
        return []


def _scope_for(s, path):
    for d in s.paths:
        if path_matches(d, path):
            return d
    return path


def _note(level, a, b, a_h, b_h):
    if level == "same-hunk":
        return "%s and %s change overlapping lines in the same region" % (a, b)
    if level == "overlapping":
        return "%s and %s touch nearby lines (%s vs %s)" % (a, b, _fmt(a_h), _fmt(b_h))
    if level == "rename":
        return "%s and %s both touch this path and one deletes or renames it" % (a, b)
    return "%s and %s edit the same file in separate regions (%s vs %s)" % (a, b, _fmt(a_h), _fmt(b_h))


def _fmt(hunks):
    if not hunks:
        return "whole file"
    return ", ".join("%d-%d" % (h[0], h[1]) for h in hunks[:3])


# --------------------------------------------------------------------------- #
# top level
# --------------------------------------------------------------------------- #

def build_snapshot(repo=None, base=None, include_remotes=True, untracked=True,
                   with_collisions=True, stale_after_hours=72, window=DEFAULT_MTIME_WINDOW):
    git = Git.detect(repo)
    root = git.toplevel()
    warnings = []
    try:
        chosen_base = base or git.default_branch()
    except GitError as exc:
        warnings.append(str(exc))
        chosen_base = git.head_ref() or "HEAD"

    head_branch = git.head_ref()
    snap = Snapshot(repo=root, generated=now_iso(), base=chosen_base,
                    head_branch=head_branch, head_sha=git.head_sha(),
                    default_branch=chosen_base,
                    git_version=".".join(str(x) for x in git.version()))

    snap.refs = collect_refs(git, chosen_base, head_branch, warnings)
    if not snap.refs:
        warnings.append("snapshot has zero refs - nothing to brief on")

    snap.worktrees = collect_worktrees(git, warnings, untracked=untracked)
    snap.stashes = git.stash_list()

    from .store import Ledger
    ledger = Ledger(root)
    sessions = ledger.sessions(stale_after_hours=stale_after_hours)
    snap.claims = ledger.claims()
    snap.sessions = sessions

    wt = snap.head_worktree()
    if wt:
        snap.clusters = cluster_changes(wt.dirty, window=window,
                                        new_roots=getattr(wt, "new_roots", ()))
        _add_inferred_sessions(snap, sessions)
    else:
        warnings.append("no readable worktree; working-tree state unknown")

    if with_collisions:
        snap.collisions = find_collisions(snap)
    snap.warnings = warnings
    return snap, ledger


def _add_inferred_sessions(snap, declared):
    """When nobody declared anything, present clusters as inferred lanes.

    Labelled `inferred:working-tree` everywhere they appear. They exist so a
    fresh session still gets a useful brief in a repo where no agent ever ran
    `muster claim`. Anything already covered by a real claim is left alone.
    """
    wt = snap.head_worktree()
    if not wt:
        return
    claimed = {f.path for f in wt.dirty
               for s in declared
               for d in s.paths if path_matches(d, f.path)}
    for c in snap.clusters:
        rest = [p for p in c.paths if p not in claimed]
        if not rest:
            continue
        when = (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(c.last_mtime))
                if c.last_mtime else "")
        snap.sessions.append(Session(
            id="lane:" + _slug(c.name),
            harness="unattributed",
            intent=c.reason,
            branch=snap.head_branch,
            worktree=snap.repo,
            paths=rest[:400],
            status="active",
            updated=when,
            source="inferred:working-tree",
        ))


def _epoch_of(iso):
    """Sort key for an ISO committer date; undated refs sort last."""
    if not iso:
        return 0.0
    try:
        return -time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0


def _slug(text):
    out = []
    for ch in text.lower():
        out.append(ch if ch.isalnum() else "-")
    s = "".join(out).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:32] or "lane"
