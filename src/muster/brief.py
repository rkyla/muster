
"""Rendering the brief: the thing another agent actually reads.

Written for a machine reader first. Rules:

* Numbers and paths come from the snapshot; nothing is embellished.
* Inferred attribution is labelled `inferred` and never presented as a fact about
  a person.
* An empty section says so explicitly, because "no other lanes" and "I could not
  see" have to be distinguishable.
"""

from __future__ import annotations

import os
import time

from .model import Snapshot
from .observe import path_matches, _slug

SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def _ago(iso_or_ts):
    if isinstance(iso_or_ts, (int, float)):
        if not iso_or_ts:
            return "unknown time"
        delta = time.time() - iso_or_ts
    else:
        if not iso_or_ts:
            return "unknown time"
        try:
            delta = time.time() - time.mktime(time.strptime(iso_or_ts[:19], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, OverflowError):
            return "unknown time"
    if delta < 0:
        return "just now"
    m = delta / 60
    if m < 60:
        return "%dm ago" % int(m)
    h = m / 60
    if h < 48:
        return "%.0fh ago" % h
    return "%.0fd ago" % (h / 24)


def _size(fc):
    bits = []
    if fc.lines_added > 0:
        bits.append("+%d" % fc.lines_added)
    if fc.lines_deleted > 0:
        bits.append("-%d" % fc.lines_deleted)
    return ("(%s)" % "/".join(bits)) if bits else ""


def _short(path, n=58):
    """Middle-truncate. The filename is the informative part; the prefix is not.

    The arithmetic is spelled out because the obvious version overruns `n` by a
    couple of characters, and a truncated path that is longer than the limit is
    worse than no truncation.
    """
    if len(path) <= n:
        return path
    head = path.split("/")[0]
    tail = os.path.basename(path)
    sep = "/.../"
    if len(head) + len(sep) + len(tail) > n:
        # Not even the first directory, the elision and the filename fit.
        return "..." + path[-(n - 3):]
    spare = n - len(head) - len(sep) - len(tail)
    mid = path[len(head) + 1: len(path) - len(tail) - 1]
    if mid and spare >= 4:
        keep_mid = min(len(mid), spare - 1)      # -1 for the "/" before the name
        # The slice can start on a separator, which would render as `a/...//b`.
        return head + sep + mid[-keep_mid:].lstrip("/") + "/" + tail
    return head + sep + tail


# --------------------------------------------------------------------------- #

def _me_block(snap: Snapshot, me):
    lines = []
    s = snap.session(me) if me else None
    who = me or "unidentified session"
    if s:
        lines.append("YOU")
        lines.append("  session %s  [%s, %s]" % (s.id, s.harness, s.source))
        if s.intent:
            lines.append("  intent: %s" % s.intent)
        if s.paths:
            lines.append("  declared scope: %s" % ", ".join(s.paths[:8]))
        lines.append("  status %s, updated %s" % (s.status, _ago(s.updated)))
    else:
        lines.append("YOU")
        lines.append("  session %s" % who)
        lines.append("  not declared - run `muster claim --intent \"...\" --paths a,b` "
                     "so other sessions can see you")
    return lines, s


def _lane_lines(snap: Snapshot, me, limit=12):
    """Other lanes: uncommitted clusters, other refs, declared sessions."""
    out = []
    wt = snap.head_worktree()
    dirty_by_path = {f.path: f for f in (wt.dirty if wt else [])}

    inferred = [s for s in snap.sessions if s.source.startswith("inferred")]
    declared = [s for s in snap.sessions if not s.source.startswith("inferred") and s.id != me]

    if inferred:
        out.append("UNCOMMITTED WORK IN THIS WORKING TREE - %d lane(s), attribution inferred"
                   % len(inferred))
        clusters = {c.name: c for c in snap.clusters}
        for s in inferred[:limit]:
            name = s.id.split(":", 1)[1]
            cluster = next((c for c in snap.clusters
                            if _slug(c.name) == name or c.name == name), None)
            paths = s.paths or []
            conf = cluster.confidence if cluster else "medium"
            out.append("  - %-34s %3d file(s)  %-8s %s"
                       % (_short(name, 34), len(paths), conf, _ago(s.updated)))
            sizes = ", ".join("%s%s" % (_short(p, 44),
                                        _size(dirty_by_path[p]) if p in dirty_by_path else "")
                              for p in paths[:3])
            more = "  +%d more" % (len(paths) - 3) if len(paths) > 3 else ""
            out.append("      %s%s" % (sizes, more))
            if s.intent:
                out.append("      why: %s" % s.intent)
        if len(inferred) > limit:
            rest = sum(len(s.paths) for s in inferred[limit:])
            out.append("  ... %d smaller lane(s), %d file(s): muster brief --limit 99"
                       % (len(inferred) - limit, rest))
    else:
        out.append("UNCOMMITTED WORK IN THIS WORKING TREE - none")

    if declared:
        out.append("")
        out.append("DECLARED SESSIONS - %d other session(s)" % len(declared))
        for s in declared[:limit]:
            out.append("  - %s [%s] %s" % (s.id, s.status, s.harness))
            if s.intent:
                out.append("      intent: %s" % s.intent)
            if s.paths:
                out.append("      scope: %s" % ", ".join(s.paths[:6]))
            out.append("      updated %s" % _ago(s.updated))

    refs = [r for r in snap.refs if not r.is_base and (r.ahead or r.files)]
    if refs:
        out.append("")
        out.append("OTHER BRANCHES - %d with work not in %s" % (len(refs), snap.base))
        for r in refs[:limit]:
            tag = "merged into %s" % r.base if r.merged_into_base else \
                  ("%d ahead / %d behind" % (r.ahead, r.behind))
            out.append("  - %s  %s  [%s]" % (r.name, tag, _ago(r.committer_date)))
            if r.commits:
                out.append("      %s" % "; ".join(c["subject"][:60] for c in r.commits[:2]))
            if r.files:
                out.append("      %d file%s touched: %s" % (
                    len(r.files), "" if len(r.files) == 1 else "s",
                    ", ".join(_short(f.path, 40) for f in r.files[:3])))
        if len(refs) > limit:
            out.append("  ... %d more: muster features" % (len(refs) - limit))
    else:
        out.append("")
        out.append("OTHER BRANCHES - none ahead of %s" % snap.base)
    return out


def _collision_lines(snap, me, limit=10):
    cols = snap.collisions
    if not cols:
        return ["COLLISIONS - none found between your working tree and other lanes"]
    high = [c for c in cols if c.severity == "high"]
    med = [c for c in cols if c.severity == "medium"]
    out = ["COLLISIONS - %d high, %d medium, %d low" % (len(high), len(med), len(cols) - len(high) - len(med))]
    for c in (high + med)[:limit]:
        out.append("  %-6s %-38s %s" % (c.severity.upper(), _short(c.path, 38), c.level))
        out.append("          %s" % c.note)
    if len(cols) > limit:
        out.append("  ... %d more: muster map" % (len(cols) - limit))
    return out


def _watch_lines(snap):
    out = []
    if snap.head_branch and snap.head_branch != snap.base:
        head = [r for r in snap.refs if r.is_head]
        if head and head[0].behind:
            out.append("your branch is %d commits behind %s" % (head[0].behind, snap.base))
    merged = [r for r in snap.refs if r.merged_into_base and not r.is_base]
    if merged:
        out.append("%d branch(es) already merged, safe to delete: %s"
                   % (len(merged), ", ".join(r.name for r in merged[:4])))
    if snap.stashes:
        out.append("%d stash(es) holding work nothing else can see: %s"
                   % (len(snap.stashes), snap.stashes[0][:60]))
    wt = snap.head_worktree()
    if wt:
        old_untracked = [f for f in wt.dirty if f.status == "?" and f.mtime
                         and (time.time() - f.mtime) > 14 * 86400]
        if old_untracked:
            out.append("%d untracked file(s) untouched for over 14 days - possibly abandoned: %s"
                       % (len(old_untracked), ", ".join(_short(f.path, 40) for f in old_untracked[:3])))
        big = [f for f in wt.dirty if f.lines_added > 400]
        if big:
            out.append("%d uncommitted file(s) over 400 added lines - commit or split them: %s"
                       % (len(big), ", ".join(_short(f.path, 40) for f in big[:3])))
    stale = [s for s in snap.sessions if s.status == "stale"]
    if stale:
        out.append("%d session(s) marked stale (no update recently): %s"
                   % (len(stale), ", ".join(s.id for s in stale[:3])))
    for w in snap.warnings:
        out.append("observation warning: %s" % w)
    return (["WATCH OUT"] + ["  - " + l for l in out]) if out else []


def _next_lines(snap, me):
    wt = snap.head_worktree()
    out = []
    if wt and wt.dirty:
        out.append("muster settle            # split this working tree into reviewable lanes")
    refs = [r for r in snap.refs if not r.is_base and r.ahead and not r.merged_into_base]
    if refs:
        out.append("muster plan %s   # what integrating it would do" % refs[0].name)
    if any(c.severity == "high" for c in snap.collisions):
        out.append("muster touch <path>      # before editing a file another lane is in")
    if not any(not s.source.startswith("inferred") for s in snap.sessions):
        out.append("muster claim --intent \"...\" --paths a,b   # tell other sessions you are here")
    return (["NEXT"] + ["  " + l for l in out]) if out else []


def render_brief(snap: Snapshot, me=None, fmt="text", limit=12):
    if fmt == "json":
        payload = snap.to_dict()
        payload["me"] = me
        import json
        return json.dumps(payload, indent=2)

    lines = []
    head = "muster brief  %s" % snap.repo
    lines.append(head)
    lines.append("base %s · you on %s · observed %s · git %s"
                 % (snap.base, snap.head_branch or "detached %s" % (snap.head_sha or "?")[:9],
                    snap.generated, snap.git_version))
    lines.append("")
    block, _ = _me_block(snap, me)
    lines += block
    lines.append("")
    lines += _lane_lines(snap, me, limit=limit)
    lines.append("")
    lines += _collision_lines(snap, me)
    watch = _watch_lines(snap)
    if watch:
        lines.append("")
        lines += watch
    nxt = _next_lines(snap, me)
    if nxt:
        lines.append("")
        lines += nxt
    if fmt == "md":
        return _to_md(lines)
    return "\n".join(lines)


def _to_md(lines):
    """Same content, markdown-shaped, for pasting into a report or a prompt."""
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append("")
        elif stripped.startswith("muster brief"):
            out.append("# " + stripped)
        elif stripped.isupper() and len(stripped) < 80:
            out.append("## " + stripped)
        elif line.startswith("      "):
            out.append("  - " + stripped)
        elif line.startswith("  "):
            out.append("- " + stripped)
        else:
            out.append(stripped)
    return "\n".join(out)


# --------------------------------------------------------------------------- #

def verdict_for(snap: Snapshot, paths, me=None):
    """Answer: is it safe for me to edit these files right now?"""
    wt = snap.head_worktree()
    dirty = {f.path: f for f in (wt.dirty if wt else [])}
    verdicts = []
    for path in paths:
        hits = [c for c in snap.collisions
                if c.path == path or (c.path.endswith("/") and path.startswith(c.path))]
        owners = [s for s in snap.sessions
                  if s.id != me and s.status != "done"
                  and any(path_matches(d, path) for d in (s.paths or []))]
        worst = "safe"
        reasons = []
        sev_rank = {"safe": 0, "low": 1, "medium": 2, "high": 3}

        def _raise(level):
            nonlocal worst
            if sev_rank.get(level, 0) > sev_rank[worst]:
                worst = level

        for c in hits:
            _raise(c.severity)
            reasons.append("%s vs %s: %s" % (c.a, c.b, c.note))
        # A declared owner is a real conflict. An inferred lane may be the
        # caller's own uncommitted work, so it is reported but must not escalate:
        # a gate that cries wolf is a gate agents learn to ignore.
        for s in owners:
            if s.source.startswith("inferred"):
                _raise("low")
                reasons.append("%s is an unattributed lane covering this path (%s)"
                               % (s.id, s.intent or "no intent given"))
            else:
                _raise("medium")
                reasons.append("%s declared this path (%s)" % (s.id, s.intent or "no intent given"))
        if path in dirty and worst == "safe":
            reasons.append("already modified in this working tree by you or an unattributed lane")
        verdicts.append({"path": path, "verdict": worst, "reasons": reasons,
                         "dirty_here": path in dirty,
                         "owners": [s.id for s in owners]})
    overall = "safe"
    rank = {"safe": 0, "low": 1, "medium": 2, "high": 3}
    for v in verdicts:
        if rank[v["verdict"]] > rank[overall]:
            overall = v["verdict"]
    return {"verdict": overall, "files": verdicts}


def render_verdict(res, fmt="text"):
    if fmt == "json":
        import json
        return json.dumps(res, indent=2)
    mark = {"safe": "SAFE", "low": "FYI", "medium": "CAUTION", "high": "STOP"}
    header = {"safe": "no other lane touches these paths",
              "low": "nothing declared touches these paths; unattributed work in this tree does",
              "medium": "a declared session overlaps these paths",
              "high": "another lane changes the same lines"}
    lines = ["%s - %s" % (mark[res["verdict"]], header[res["verdict"]])]
    for v in res["files"]:
        lines.append("  %-8s %s" % (v["verdict"].upper(), v["path"]))
        for r in v["reasons"]:
            lines.append("             %s" % r)
        if not v["reasons"]:
            lines.append("             nothing observed")
    return "\n".join(lines)


def render_map(snap: Snapshot, fmt="text"):
    if fmt == "json":
        import json
        return json.dumps([c.to_dict() for c in snap.collisions], indent=2)
    if not snap.collisions:
        return "no collisions observed"
    lines = ["%-40s %-22s %-22s %-12s %s" % ("PATH", "A", "B", "LEVEL", "SEVERITY")]
    lines.append("-" * 118)
    for c in sorted(snap.collisions, key=lambda c: (SEV_ORDER.get(c.severity, 3), c.path)):
        lines.append("%-40s %-22s %-22s %-12s %s"
                     % (_short(c.path, 40), _short(c.a, 22), _short(c.b, 22), c.level, c.severity))
    lines.append("")
    lines.append("%d collision(s): %d high, %d medium, %d low"
                 % (len(snap.collisions),
                    sum(1 for c in snap.collisions if c.severity == "high"),
                    sum(1 for c in snap.collisions if c.severity == "medium"),
                    sum(1 for c in snap.collisions if c.severity == "low")))
    return "\n".join(lines)
