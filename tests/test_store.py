
"""The ledger: concurrent writers, and nothing lost when they collide."""
import datetime
import json
import os
import sqlite3
import subprocess
import sys
import threading

from muster.model import Claim, Session, now_iso
from muster.store import Ledger, state_dir_for


def test_sessions_upsert_by_id(repo):
    led = Ledger(repo)
    led.upsert_session(Session(id="prime-agent/one", harness="prime-agent", intent="a"))
    led.upsert_session(Session(id="prime-agent/one", harness="prime-agent", intent="b"))
    rows = [r for r in led.sessions() if r.id == "prime-agent/one"]
    assert len(rows) == 1
    assert rows[0].intent == "b"


def test_events_are_append_only(repo):
    led = Ledger(repo)
    for i in range(5):
        led.record("claim", session_id="s", note=str(i))
    events = led.recent_events(limit=10)
    assert len(events) == 5
    assert [e["detail"]["note"] for e in events] == ["4", "3", "2", "1", "0"]


def test_events_are_mirrored_to_jsonl_for_auditing(repo):
    led = Ledger(repo)
    led.record("merge", session_id="s", branch="muster/x")
    lines = open(os.path.join(led.dir, "events.jsonl")).read().strip().splitlines()
    assert json.loads(lines[-1])["detail"]["branch"] == "muster/x"


def test_claims_are_per_session_and_stay_readable(repo):
    led = Ledger(repo)
    led.add_claim(Claim(session_id="a", paths=["site/"], intent="hero"))
    led.add_claim(Claim(session_id="b", paths=["api/"], intent="upload"))
    assert [c.intent for c in led.claims("a")] == ["hero"]
    assert len(led.claims()) == 2
    assert led.claims("a")[0].created, "a claim with no timestamp is unauditable"


def test_busy_database_is_retried_not_raised(repo):
    """A second writer holding the lock must not turn into a traceback."""
    led = Ledger(repo)
    led.record("observe", note="first")
    hold = threading.Event()
    released = threading.Event()

    def hog():
        other = sqlite3.connect(led.db_path, timeout=5.0, isolation_level=None)
        other.execute("BEGIN IMMEDIATE")
        hold.set()
        released.wait(3.0)
        other.execute("COMMIT")
        other.close()

    th = threading.Thread(target=hog)
    th.start()
    hold.wait(5)
    try:
        led.record("observe", note="second")   # blocks on the lock, then succeeds
    finally:
        released.set()
        th.join(10)
    notes = [e["detail"].get("note") for e in led.recent_events(limit=10)]
    assert "second" in notes


def test_many_threads_write_without_losing_rows(repo):
    led = Ledger(repo)
    errors = []

    def worker(n):
        try:
            for i in range(12):
                led.record("observe", session_id="t%d" % n, i=i)
        except Exception as exc:            # noqa: BLE001 - any failure is a finding
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(led.recent_events(limit=1000)) == 8 * 12


def test_ledger_is_shared_across_processes(repo):
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    code = ("import sys; sys.path.insert(0, %r);"
            "from muster.store import Ledger;"
            "Ledger(%r).record('observe', session_id='child');" % (src, repo))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert proc.returncode == 0, proc.stderr.decode()
    assert any(e["session_id"] == "child" for e in Ledger(repo).recent_events(limit=50))


def test_state_dir_is_outside_the_repo_by_default(tmp_path, monkeypatch):
    """A read-only command must not create untracked files in the repo."""
    monkeypatch.setenv("MUSTER_STATE_DIR", str(tmp_path / "state"))
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    led = Ledger(repo)
    assert str(tmp_path / "state") in led.dir
    assert not os.path.exists(os.path.join(repo, ".muster"))


def test_an_existing_dot_muster_opts_the_repo_in(tmp_path, monkeypatch):
    monkeypatch.delenv("MUSTER_STATE_DIR", raising=False)
    repo = str(tmp_path / "repo")
    os.makedirs(os.path.join(repo, ".muster"))
    assert state_dir_for(repo) == os.path.join(repo, ".muster")
    assert Ledger(repo).in_repo is True


def test_gitignore_is_only_touched_on_init(repo):
    led = Ledger(repo)
    gi = os.path.join(repo, ".gitignore")
    before = open(gi).read() if os.path.exists(gi) else ""
    assert ".muster/" not in before
    assert led.ensure_gitignored() is True
    assert ".muster/" in open(gi).read()
    assert led.ensure_gitignored() is False, "must not append twice"


def test_old_active_sessions_are_reported_stale(repo):
    led = Ledger(repo)
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(days=30)).isoformat(timespec="seconds")
    led.upsert_session(Session(id="stale/one", harness="x", status="active"))
    led.upsert_session(Session(id="fresh/one", harness="x", status="active"))
    # upsert always stamps "now" - that is the point of a claim - so age the row
    # the way time does. Staleness is under test here, not the writer.
    con = sqlite3.connect(led.db_path)
    con.execute("UPDATE sessions SET updated=? WHERE id='stale/one'", (old,))
    con.commit()
    con.close()
    by_id = {s.id: s for s in led.sessions()}
    assert by_id["stale/one"].status == "stale"
    assert by_id["fresh/one"].status == "active"


def test_done_sessions_can_be_filtered_out(repo):
    led = Ledger(repo)
    led.upsert_session(Session(id="a", status="active", updated=now_iso()))
    led.upsert_session(Session(id="b", status="done", updated=now_iso()))
    assert {s.id for s in led.sessions()} == {"a", "b"}
    assert {s.id for s in led.sessions(include_done=False)} == {"a"}


def test_snapshots_are_kept_separately_and_pruned(repo):
    from muster.observe import build_snapshot
    led = Ledger(repo)
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    paths = {led.save_snapshot(snap) for _ in range(3)}
    assert len(paths) == 3, "two observations in one second must not overwrite"
    assert os.path.exists(led.latest_snapshot_path())
    assert open(led.latest_snapshot_path()).read() == snap.to_json()


def test_current_session_file_is_the_last_resort(repo):
    led = Ledger(repo)
    led.set_current("declared/one")
    assert led.get_current() == "declared/one"


def test_status_counts_what_is_stored(repo):
    led = Ledger(repo)
    led.upsert_session(Session(id="a", updated=now_iso()))
    led.record("observe")
    st = led.status()
    assert st["sessions"] >= 1
    assert st["events"] >= 1
