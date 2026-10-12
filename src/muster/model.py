
"""Data model for a muster snapshot.

A snapshot is a point-in-time observation of one repository across every session
touching it. It serialises to JSON so it can be stored, diffed, pushed to a git
ref, and read by an agent without re-running git.
"""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import dataclass, field

SCHEMA = "muster/snapshot/2"


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass
class Session:
    """One declared or inferred agent session working in the repo."""

    id: str
    harness: str = "unknown"        # claude-code | opencode | codex | prime-agent | human
    intent: str = ""                # what it says it is building
    branch: str | None = None
    worktree: str | None = None
    paths: list[str] = field(default_factory=list)
    status: str = "active"          # active | idle | done | stale
    started: str = ""
    updated: str = ""
    summary: str = ""               # what it says it finished
    source: str = "declared"        # declared | inferred | env
    pid: int | None = None

    def to_dict(self):
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d):
        keep = {f.name for f in dataclasses.fields(Session)}
        return Session(**{k: v for k, v in d.items() if k in keep})


@dataclass
class Claim:
    """A soft, advisory claim over paths. Not enforced by git; surfaced in briefs."""

    session_id: str
    paths: list[str] = field(default_factory=list)
    intent: str = ""
    created: str = ""
    kind: str = "claim"             # claim | done
    summary: str = ""

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclass
class FileChange:
    path: str
    status: str = "M"               # A/M/D/R/T/U/?
    old_path: str | None = None
    lines_added: int = -1
    lines_deleted: int = -1
    hunks: list[list[int]] = field(default_factory=list)
    mtime: float = 0.0

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclass
class RefState:
    """A branch (local or remote) and what it contains relative to the base."""

    name: str
    kind: str                       # branch | remote
    sha: str
    committer_date: str = ""
    author: str = ""
    subject: str = ""
    base: str = ""
    merge_base: str = ""
    ahead: int = 0
    behind: int = 0
    commits: list[dict] = field(default_factory=list)
    files: list[FileChange] = field(default_factory=list)
    is_base: bool = False
    is_head: bool = False
    merged_into_base: bool = False

    def to_dict(self):
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d):
        keep = {f.name for f in dataclasses.fields(RefState)} - {"commits", "files"}
        r = RefState(**{k: v for k, v in d.items() if k in keep})
        r.commits = list(d.get("commits", []))
        r.files = [FileChange(**f) for f in d.get("files", [])]
        return r


@dataclass
class WorktreeState:
    path: str
    branch: str | None = None
    head: str = ""
    detached: bool = False
    is_main: bool = False
    dirty: list[FileChange] = field(default_factory=list)
    new_roots: list[str] = field(default_factory=list)
    session_id: str | None = None

    def to_dict(self):
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d):
        keep = {f.name for f in dataclasses.fields(WorktreeState)} - {"dirty"}
        # new_roots is carried through the generic keep-set above
        w = WorktreeState(**{k: v for k, v in d.items() if k in keep})
        w.dirty = [FileChange(**f) for f in d.get("dirty", [])]
        return w


@dataclass
class Cluster:
    """A group of changes that read as one piece of functionality."""

    name: str
    paths: list[str] = field(default_factory=list)
    reason: str = ""
    confidence: str = "medium"      # high | medium | low
    first_mtime: float = 0.0
    last_mtime: float = 0.0
    added: int = 0
    deleted: int = 0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclass
class Collision:
    """Two actors touching the same code."""

    path: str
    a: str
    b: str
    level: str                      # same-hunk | overlapping | same-file | rename
    severity: str = "medium"        # high | medium | low
    a_hunks: list[list[int]] = field(default_factory=list)
    b_hunks: list[list[int]] = field(default_factory=list)
    note: str = ""

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclass
class Snapshot:
    repo: str
    generated: str
    base: str
    head_branch: str | None = None
    head_sha: str | None = None
    default_branch: str = ""
    git_version: str = ""
    refs: list[RefState] = field(default_factory=list)
    worktrees: list[WorktreeState] = field(default_factory=list)
    sessions: list[Session] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    clusters: list[Cluster] = field(default_factory=list)
    collisions: list[Collision] = field(default_factory=list)
    stashes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema: str = SCHEMA

    def ref(self, name):
        if not name:
            return None
        for r in self.refs:
            if r.name == name or r.name == "origin/" + name or r.name.endswith("/" + name):
                return r
        return None

    def session(self, sid):
        for s in self.sessions:
            if s.id == sid:
                return s
        return None

    def head_worktree(self):
        for w in self.worktrees:
            if w.is_main:
                return w
        return self.worktrees[0] if self.worktrees else None

    def active_others(self, me=None):
        return [s for s in self.sessions if s.id != me and s.status in ("active", "idle")]

    def to_dict(self):
        d = {
            "schema": self.schema,
            "repo": self.repo,
            "generated": self.generated,
            "base": self.base,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha,
            "default_branch": self.default_branch,
            "git_version": self.git_version,
            "refs": [r.to_dict() for r in self.refs],
            "worktrees": [w.to_dict() for w in self.worktrees],
            "sessions": [s.to_dict() for s in self.sessions],
            "claims": [c.to_dict() for c in self.claims],
            "clusters": [c.to_dict() for c in self.clusters],
            "collisions": [c.to_dict() for c in self.collisions],
            "stashes": self.stashes,
            "warnings": self.warnings,
        }
        return d

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def from_dict(d):
        s = Snapshot(
            repo=d["repo"], generated=d["generated"], base=d["base"],
            head_branch=d.get("head_branch"), head_sha=d.get("head_sha"),
            default_branch=d.get("default_branch", ""),
            git_version=d.get("git_version", ""),
        )
        s.refs = [RefState.from_dict(x) for x in d.get("refs", [])]
        s.worktrees = [WorktreeState.from_dict(x) for x in d.get("worktrees", [])]
        s.sessions = [Session.from_dict(x) for x in d.get("sessions", [])]
        s.claims = [Claim(**x) for x in d.get("claims", [])]
        s.clusters = [Cluster(**x) for x in d.get("clusters", [])]
        s.collisions = [Collision(**x) for x in d.get("collisions", [])]
        s.stashes = list(d.get("stashes", []))
        s.warnings = list(d.get("warnings", []))
        return s

    @staticmethod
    def load(path):
        with open(path) as fh:
            return Snapshot.from_dict(json.load(fh))
