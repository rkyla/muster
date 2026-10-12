
"""The ledger: durable local state for one repository.

Layout inside the repo (gitignored):

    .muster/
      ledger.db          sqlite: sessions, claims, events
      CURRENT            session id for shells with no harness env
      config.toml        optional config
      snapshots/*.json   immutable observation snapshots (audit trail)
      latest.json        pointer to the newest snapshot
      events.jsonl       append-only log of orchestration decisions

Five sessions write concurrently, so the database runs in WAL mode with short
transactions and a bounded retry on SQLITE_BUSY.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager

from .model import Claim, Session, now_iso

SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  harness TEXT NOT NULL DEFAULT 'unknown',
  intent TEXT NOT NULL DEFAULT '',
  branch TEXT,
  worktree TEXT,
  paths TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  started TEXT NOT NULL DEFAULT '',
  updated TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'declared',
  pid INTEGER
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  paths TEXT NOT NULL DEFAULT '[]',
  intent TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'claim',
  summary TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  session_id TEXT,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_claims_session ON claims(session_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
"""


def state_dir_for(repo_root):
    """Where a repo's ledger lives.

    Observation must stay read-only. Creating `.muster/` inside a repository on a
    `muster brief` would add untracked files to the very status output this tool
    exists to clarify, so state lives under the user state dir unless the repo has
    opted in by running `muster init` (which creates `<repo>/.muster/`).
    """
    local = os.path.join(repo_root, ".muster")
    if os.path.isdir(local):
        return local
    import hashlib
    base = os.environ.get("MUSTER_STATE_DIR") or os.path.join(
        os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "muster")
    key = hashlib.sha1(os.path.realpath(repo_root).encode()).hexdigest()[:12]
    return os.path.join(base, key)


def _quiet_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


class Ledger:
    def __init__(self, repo_root, state_dir=None):
        self.root = repo_root
        self.dir = state_dir or state_dir_for(repo_root)
        self.in_repo = os.path.abspath(self.dir) == os.path.abspath(
            os.path.join(repo_root, ".muster"))
        self.db_path = os.path.join(self.dir, "ledger.db")
        self.snap_dir = os.path.join(self.dir, "snapshots")
        os.makedirs(self.snap_dir, exist_ok=True)
        self._init()

    # ---- low level -------------------------------------------------------

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=2000")
        return con

    def _init(self):
        con = self._connect()
        try:
            con.executescript(_DDL)
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema', ?)",
                        (str(SCHEMA_VERSION),))
        finally:
            con.close()

    @contextmanager
    def _tx(self):
        """One short IMMEDIATE transaction. Never held across git calls."""
        con = self._connect()
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            con.close()
            raise
        else:
            con.execute("COMMIT")
            con.close()

    def _with_tx(self, fn, retries=6):
        """Run fn(con) in a transaction, retrying writer-lock contention.

        Five sessions can claim at the same moment; SQLITE_BUSY is expected, not
        a reason to lose a claim.
        """
        last = None
        for attempt in range(retries + 1):
            try:
                with self._tx() as con:
                    return fn(con)
            except sqlite3.OperationalError as exc:
                last = exc
                if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                    raise
                time.sleep(0.05 * (attempt + 1))
        raise last

    # ---- sessions --------------------------------------------------------

    def upsert_session(self, s: Session):
        s.updated = now_iso()
        if not s.started:
            s.started = s.updated
        def _write(con):
            con.execute(
                """INSERT INTO sessions(id, harness, intent, branch, worktree, paths, status,
                                        started, updated, summary, source, pid)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     harness=excluded.harness, intent=excluded.intent, branch=excluded.branch,
                     worktree=excluded.worktree, paths=excluded.paths, status=excluded.status,
                     updated=excluded.updated, summary=excluded.summary, source=excluded.source,
                     pid=excluded.pid""",
                (s.id, s.harness, s.intent, s.branch, s.worktree, json.dumps(s.paths),
                 s.status, s.started, s.updated, s.summary, s.source, s.pid),
            )
            return None
        self._with_tx(_write)
        return s

    def get_session(self, sid):
        con = self._connect()
        try:
            row = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        finally:
            con.close()
        return self._row_to_session(row) if row else None

    def sessions(self, include_done=True, stale_after_hours=72):
        con = self._connect()
        try:
            rows = con.execute("SELECT * FROM sessions ORDER BY updated DESC").fetchall()
        finally:
            con.close()
        out = []
        cutoff = time.time() - stale_after_hours * 3600
        for row in rows:
            s = self._row_to_session(row)
            if s.status == "active" and _epoch(s.updated) and _epoch(s.updated) < cutoff:
                s.status = "stale"
            if s.status == "done" and not include_done:
                continue
            out.append(s)
        return out

    def mark_done(self, sid, summary=""):
        self._with_tx(lambda con: con.execute(
            "UPDATE sessions SET status='done', summary=?, updated=? WHERE id=?",
            (summary, now_iso(), sid)))

    def forget(self, sid):
        def _del(con):
            con.execute("DELETE FROM sessions WHERE id=?", (sid,))
            con.execute("DELETE FROM claims WHERE session_id=?", (sid,))
        self._with_tx(_del)

    @staticmethod
    def _row_to_session(row):
        return Session(
            id=row["id"], harness=row["harness"], intent=row["intent"], branch=row["branch"],
            worktree=row["worktree"], paths=json.loads(row["paths"] or "[]"),
            status=row["status"], started=row["started"], updated=row["updated"],
            summary=row["summary"], source=row["source"], pid=row["pid"],
        )

    # ---- claims ----------------------------------------------------------

    def add_claim(self, c: Claim):
        if not c.created:
            c.created = now_iso()
        def _ins(con):
            con.execute("INSERT INTO claims(session_id, paths, intent, created, kind, summary) "
                        "VALUES(?,?,?,?,?,?)",
                        (c.session_id, json.dumps(c.paths), c.intent, c.created, c.kind, c.summary))
            con.execute("INSERT INTO events(ts, session_id, kind, detail) VALUES(?,?,?,?)",
                        (c.created, c.session_id, "claim",
                         json.dumps({"paths": c.paths, "intent": c.intent})))
        self._with_tx(_ins)
        return c

    def claims(self, session_id=None):
        con = self._connect()
        try:
            if session_id:
                rows = con.execute("SELECT * FROM claims WHERE session_id=? ORDER BY created",
                                   (session_id,)).fetchall()
            else:
                rows = con.execute("SELECT * FROM claims ORDER BY created").fetchall()
        finally:
            con.close()
        return [Claim(session_id=r["session_id"], paths=json.loads(r["paths"] or "[]"),
                      intent=r["intent"], created=r["created"], kind=r["kind"],
                      summary=r["summary"]) for r in rows]

    # ---- events ----------------------------------------------------------

    def record(self, kind, session_id=None, **detail):
        ts = now_iso()
        self._with_tx(lambda con: con.execute(
            "INSERT INTO events(ts, session_id, kind, detail) VALUES(?,?,?,?)",
            (ts, session_id, kind, json.dumps(detail, default=str))))
        try:
            with open(os.path.join(self.dir, "events.jsonl"), "a") as fh:
                fh.write(json.dumps({"ts": ts, "session_id": session_id, "kind": kind,
                                     "detail": detail}, default=str) + "\n")
        except OSError:
            pass
        return ts

    def recent_events(self, limit=50):
        con = self._connect()
        try:
            rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            con.close()
        return [{"ts": r["ts"], "session_id": r["session_id"], "kind": r["kind"],
                 "detail": json.loads(r["detail"] or "{}")} for r in rows]

    # ---- snapshots -------------------------------------------------------

    def save_snapshot(self, snap):
        """Write an audit record under a name nothing else is holding.

        Observations can land in the same second, the same millisecond and, on a
        fast machine, the same microsecond - so the timestamp is a starting point,
        not a claim. The name is taken with `link`, which fails when it is already
        used, and retried with a counter. An earlier record is never overwritten:
        an audit trail that loses rows is not an audit trail.
        """
        body = snap.to_json()
        stamp = "%s-%06d-%d" % (time.strftime("%Y%m%dT%H%M%S"),
                                int(time.time() * 1e6) % 1000000, os.getpid())
        path = None
        for attempt in range(1000):
            name = stamp if attempt == 0 else "%s-%d" % (stamp, attempt)
            candidate = os.path.join(self.snap_dir, name + ".json")
            tmp = "%s.%d.tmp" % (candidate, os.getpid())
            try:
                with open(tmp, "w") as fh:
                    fh.write(body)
                os.link(tmp, candidate)      # atomic: raises if the name is taken
                _quiet_unlink(tmp)
                path = candidate
                break
            except FileExistsError:
                _quiet_unlink(tmp)
                continue
            except OSError:
                # Filesystems without hardlinks (some network mounts, Windows
                # without privileges): the exclusive create still cannot clobber.
                _quiet_unlink(tmp)
                try:
                    fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                    with os.fdopen(fd, "w") as fh:
                        fh.write(body)
                    path = candidate
                    break
                except FileExistsError:
                    continue
                except OSError:
                    continue
        if path is None:
            return ""
        with open(os.path.join(self.dir, "latest.json"), "w") as fh:
            fh.write(path)
        self._prune_snapshots(keep=50)
        return path

    def _prune_snapshots(self, keep):
        try:
            names = sorted(n for n in os.listdir(self.snap_dir) if n.endswith(".json"))
        except OSError:
            return
        for name in names[:-keep] if keep else []:
            try:
                os.remove(os.path.join(self.snap_dir, name))
            except OSError:
                pass

    def latest_snapshot_path(self):
        ptr = os.path.join(self.dir, "latest.json")
        if not os.path.exists(ptr):
            return None
        try:
            with open(ptr) as fh:
                path = fh.read().strip()
        except OSError:
            return None
        if os.path.exists(path):
            return path
        names = sorted(n for n in os.listdir(self.snap_dir) if n.endswith(".json"))
        return os.path.join(self.snap_dir, names[-1]) if names else None

    # ---- misc ------------------------------------------------------------

    def set_current(self, sid):
        with open(os.path.join(self.dir, "CURRENT"), "w") as fh:
            fh.write(sid + "\n")

    def get_current(self):
        path = os.path.join(self.dir, "CURRENT")
        if os.path.exists(path):
            try:
                with open(path) as fh:
                    return fh.read().strip() or None
            except OSError:
                return None
        return None

    def ensure_gitignored(self):
        """Append `.muster/` to .gitignore. Called only by `muster init`, which is
        the repo opting in to in-repo state."""
        gi = os.path.join(self.root, ".gitignore")
        line = ".muster/"
        try:
            existing = open(gi).read() if os.path.exists(gi) else ""
        except OSError:
            existing = ""
        if line in existing.split():
            return False
        with open(gi, "a") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write("\n# muster: local cross-session ledger\n" + line + "\n")
        return True

    def status(self):
        con = self._connect()
        try:
            counts = {}
            for table in ("sessions", "claims", "events"):
                counts[table] = con.execute("SELECT COUNT(*) c FROM %s" % table).fetchone()["c"]
        finally:
            con.close()
        counts["snapshots"] = len([n for n in os.listdir(self.snap_dir) if n.endswith(".json")])
        counts["db_bytes"] = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return counts


def _epoch(iso):
    if not iso:
        return 0.0
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return 0.0
