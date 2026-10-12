
"""Cross-machine ledger sync over a git ref. No server.

Sessions on one machine share `.muster/ledger.db`. Sessions in different clones or
on different machines cannot see that file, so the ledger is also published as an
ordinary git ref, `refs/muster/ledger`, holding one JSON blob. Git already
replicates refs, so `git push` / `git fetch` carry session state for free, and
the ref never appears in a working tree or a PR.

Only declared state is published: session ids, intents, scopes, events. No file
contents and no commit bodies leave the machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from .gitio import Git, GitError
from .model import Claim, Session, now_iso

REF = "refs/muster/ledger"
BLOB = "ledger.json"


def repo_id(git: Git) -> str:
    """Stable identity so a pull never merges another project's sessions."""
    remotes = git.run("remote", check=False).split()
    url = ""
    if remotes:
        url = git.run("remote", "get-url", remotes[0], check=False).strip()
    if url:
        return hashlib.sha256(url.encode()).hexdigest()[:16]
    first = git.run("rev-list", "--max-parents=0", "HEAD", check=False).split()
    return hashlib.sha256((first[0] if first else git.toplevel()).encode()).hexdigest()[:16]


def _mktree(git: Git, blob_sha, name=BLOB):
    # `git mktree` wants "<mode> <type> <sha>\t<path>\n". A literal backslash-t
    # here fails with "input format error", which is exactly the kind of failure
    # that must not pass as a successful push.
    entry = "100644 blob %s\t%s\n" % (blob_sha, name)
    return git.run("mktree", stdin=entry.encode()).strip()


def export_doc(git: Git, ledger):
    sessions = [s.to_dict() for s in ledger.sessions()]
    return {
        "schema": "muster/ledger-export/1",
        "repo_id": repo_id(git),
        "repo_name": os.path.basename(git.toplevel()),
        "generated": now_iso(),
        "sessions": sessions,
        "claims": [c.to_dict() for c in ledger.claims()],
        "events": ledger.recent_events(200),
    }


def push(git: Git, ledger, remote="origin", dry_run=False):
    doc = export_doc(git, ledger)
    payload = json.dumps(doc, indent=2, sort_keys=True).encode()
    if dry_run:
        return {"ok": True, "dry_run": True, "bytes": len(payload),
                "sessions": len(doc["sessions"]), "ref": REF, "remote": remote}
    remotes = git.run("remote", check=False).split()
    if remote not in remotes:
        # Publishing to nowhere must say so; a local-only ref is not a sync.
        return {"ok": False,
                "error": "no remote named %r (this repo has: %s)"
                         % (remote, ", ".join(remotes) or "none")}
    try:
        blob = git.run("hash-object", "-w", "--stdin", stdin=payload).strip()
        tree = _mktree(git, blob)
        parent = git.run("rev-parse", "-q", "--verify", REF, check=False).strip()
        args = ["commit-tree", tree, "-m", "muster ledger %s" % now_iso()]
        if parent:
            args += ["-p", parent]
        commit = git.run(*args).strip()
        git.run("update-ref", REF, commit)
        out = git.run("push", remote, "%s:%s" % (REF, REF), check=False)
        forced = git.run("push", "--force", remote, "%s:%s" % (REF, REF), check=False) \
            if "rejected" in out.lower() or "non-fast-forward" in out.lower() else ""
        ledger.record("sync-push", branch=REF, sessions=len(doc["sessions"]))
        return {"ok": True, "ref": REF, "commit": commit[:9], "remote": remote,
                "output": (out + forced).strip()[:400], "sessions": len(doc["sessions"])}
    except GitError as exc:
        return {"ok": False, "error": str(exc)}


def fetch(git: Git, remote="origin"):
    out = git.run("fetch", remote, "%s:%s" % (REF, REF), check=False)
    if git.run("rev-parse", "-q", "--verify", REF, check=False).strip():
        return {"ok": True, "output": out.strip()[:300]}
    out2 = git.run("fetch", remote, REF, check=False)
    ok = bool(git.run("rev-parse", "-q", "--verify", "FETCH_HEAD", check=False).strip())
    return {"ok": ok, "output": (out + out2).strip()[:300], "ref": "FETCH_HEAD"}


def pull(git: Git, ledger, remote="origin", dry_run=False):
    got = fetch(git, remote)
    ref = REF if git.run("rev-parse", "-q", "--verify", REF, check=False).strip() else "FETCH_HEAD"
    if not got.get("ok"):
        return {"ok": False, "error": "nothing to fetch from %s (%s)" % (remote, got.get("output", ""))}
    raw = git.run("show", "%s:%s" % (ref, BLOB), check=False)
    if not raw.strip():
        return {"ok": False, "error": "%s has no %s blob" % (ref, BLOB)}
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        return {"ok": False, "error": "ledger blob is not JSON: %s" % exc}
    if doc.get("repo_id") != repo_id(git):
        return {"ok": False,
                "error": "remote ledger is for a different repository (repo_id %s != %s)"
                         % (doc.get("repo_id"), repo_id(git))}
    imported, skipped = [], []
    for d in doc.get("sessions", []):
        try:
            s = Session.from_dict(d)
        except TypeError:
            skipped.append(str(d)[:60])
            continue
        existing = ledger.get_session(s.id)
        if existing and (existing.updated or "") >= (s.updated or ""):
            continue
        if not dry_run:
            ledger.upsert_session(s)
        imported.append(s.id)
    if not dry_run:
        local_claims = {(c.session_id, tuple(c.paths), c.created) for c in ledger.claims()}
        for d in doc.get("claims", []):
            try:
                c = Claim(**d)
            except TypeError:
                continue
            if (c.session_id, tuple(c.paths), c.created) in local_claims:
                continue
            ledger.add_claim(c)
        ledger.record("sync-pull", remote=remote, imported=len(imported))
    return {"ok": True, "imported": imported, "skipped": skipped,
            "remote_sessions": len(doc.get("sessions", [])), "dry_run": dry_run}


def status(git: Git, ledger):
    local = git.run("rev-parse", "-q", "--verify", REF, check=False).strip()
    remote_url = git.run("config", "--get", "remote.origin.url", check=False).strip()
    return {"ref": REF, "local_commit": local[:9] if local else None,
            "remote": remote_url or None, "repo_id": repo_id(git),
            "ledger": ledger.status()}
