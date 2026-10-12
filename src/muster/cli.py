
"""muster command line.

`muster` is built to be run by an agent, so every command has a --json form, a
non-zero exit means something real, and an empty answer says why it is empty.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .brief import render_brief, render_map, render_verdict, verdict_for
from .config import load as load_config
from .config import write_default
from .digest import features, llm_available, llm_narrate
from .gitio import Git, GitError
from .hooks import install_block, install_claude_hook
from .identify import resolve_session
from .model import Claim, Session
from .observe import build_snapshot
from .orchestrate import merge, settle_apply, settle_plan, watch
from .store import Ledger
from . import sync as syncmod


def _repo(args):
    return os.path.abspath(args.repo) if getattr(args, "repo", None) else None


def _session(args, git):
    sid, harness, source = resolve_session(getattr(args, "session", None), repo=git.toplevel())
    return sid, harness, source


def _snapshot(args, cfg, with_collisions=True):
    snap, ledger = build_snapshot(
        repo=_repo(args), base=args.base or cfg.get("base"),
        include_remotes=not getattr(args, "local", False),
        untracked=not getattr(args, "no_untracked", False),
        with_collisions=with_collisions,
        stale_after_hours=cfg.get("stale_hours") or 72,
    )
    return snap, ledger


def cmd_scan(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    snap, ledger = _snapshot(args, cfg)
    path = ledger.save_snapshot(snap)
    if args.json:
        out = snap.to_dict()
        out["snapshot_path"] = path
        print(json.dumps(out, indent=2))
    else:
        wt = snap.head_worktree()
        print("scanned %s" % snap.repo)
        print("  %d ref(s), %d worktree(s), %d dirty path(s), %d session(s)"
              % (len(snap.refs), len(snap.worktrees), len(wt.dirty) if wt else 0,
                 len(snap.sessions)))
        print("  %d cluster(s), %d collision(s)" % (len(snap.clusters), len(snap.collisions)))
        print("  snapshot: %s" % path)
        for w in snap.warnings:
            print("  warning: %s" % w)
    return 0


def cmd_brief(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    snap, ledger = _snapshot(args, cfg)
    if not args.no_save:
        ledger.save_snapshot(snap)
    me, _h, _s = _session(args, Git(snap.repo))
    if args.quiet_summary:
        wt = snap.head_worktree()
        high = sum(1 for c in snap.collisions if c.severity == "high")
        print("muster: %d other lane(s), %d uncommitted file(s), %d high-severity collision(s). "
              "Run `muster brief` for detail."
              % (max(0, len(snap.sessions) - 1), len(wt.dirty) if wt else 0, high))
        return 0
    fmt = "json" if args.json else args.format
    print(render_brief(snap, me=me, fmt=fmt, limit=args.limit))
    return 0


def cmd_claim(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    git = Git.detect(_repo(args))
    sid, harness, source = _session(args, git)
    ledger = Ledger(git.toplevel())
    paths = []
    for chunk in (args.paths or []):
        paths.extend(p for p in chunk.split(",") if p.strip())
    paths = [p.strip().rstrip("/") for p in paths]
    if not paths and not args.intent:
        print("nothing to claim: pass --intent and/or --paths", file=sys.stderr)
        return 2
    existing = ledger.get_session(sid)
    if existing and args.append:
        paths = sorted(set(existing.paths) | set(paths))
    snap = None
    if not paths:
        # No explicit scope: take what this session appears to be touching.
        snap, _ = _snapshot(args, cfg, with_collisions=False)
        paths = _guess_scope(snap, sid)
    s = Session(id=sid, harness=harness, intent=args.intent or "", branch=git.head_ref(),
                worktree=git.toplevel(), paths=paths, status="active", source=source,
                pid=os.getppid())
    ledger.upsert_session(s)
    ledger.set_current(sid)
    if paths:
        ledger.add_claim(Claim(session_id=sid, paths=paths, intent=args.intent or ""))
    if args.json:
        print(json.dumps({"session": sid, "harness": harness, "source": source,
                          "paths": paths, "intent": s.intent}, indent=2))
    else:
        print("claimed as %s [%s via %s]" % (sid, harness, source))
        print("  intent: %s" % (s.intent or "(none given)"))
        print("  scope: %s" % (", ".join(paths[:12]) + (" ..." if len(paths) > 12 else "")
                               or "(none - add --paths so others can avoid you)"))
        others = [x for x in ledger.sessions() if x.id != sid and x.status != "done"]
        if others:
            print("  %d other session(s) in this repo: %s"
                  % (len(others), ", ".join(o.id for o in others[:5])))
        if snap is not None:
            clash = _clash_with(snap, sid, paths)
            for line in clash:
                print("  NOTE %s" % line)
    return 0


def _guess_scope(snap, sid):
    """Scope for a session that did not say: files it plausibly owns.

    Deliberately conservative - only clusters whose files are all in one area.
    """
    out = []
    for c in snap.clusters:
        if c.confidence == "high" and c.paths:
            top = os.path.dirname(c.paths[0]) or "."
            if top not in out:
                out.append(top)
    return out[:6]


def _clash_with(snap, sid, paths):
    from .observe import path_matches
    notes = []
    for s in snap.sessions:
        if s.id == sid or s.source.startswith("inferred"):
            continue
        for mine in paths:
            for theirs in (s.paths or []):
                if path_matches(theirs, mine) or path_matches(mine, theirs):
                    notes.append("%s also claimed %s (%s)" % (s.id, theirs, s.intent or "no intent"))
    return notes[:6]


def cmd_touch(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    snap, ledger = _snapshot(args, cfg)
    me, _h, _s = _session(args, Git(snap.repo))
    res = verdict_for(snap, args.paths, me=me)
    print(render_verdict(res, fmt=args.format))
    ledger.record("touch", session_id=me, paths=args.paths, verdict=res["verdict"])
    return 0 if res["verdict"] in ("safe", "low") else 1


def cmd_done(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    git = Git.detect(_repo(args))
    sid, harness, _source = _session(args, git)
    ledger = Ledger(git.toplevel())
    if not ledger.get_session(sid):
        print("no claim on record for %s" % sid, file=sys.stderr)
        return 1
    ledger.mark_done(sid, args.summary or "")
    ledger.record("done", session_id=sid, summary=args.summary or "")
    print("closed %s" % sid)
    if args.summary:
        print("  summary: %s" % args.summary)
    return 0


def cmd_whoami(args):
    git = Git.detect(_repo(args))
    sid, harness, source = _session(args, git)
    ledger = Ledger(git.toplevel())
    s = ledger.get_session(sid)
    if args.json:
        print(json.dumps({"session": sid, "harness": harness, "source": source,
                          "declared": bool(s), "intent": s.intent if s else "",
                          "paths": s.paths if s else []}, indent=2))
    else:
        print(sid)
        print("  harness %s, identified via %s" % (harness, source))
        print("  %s" % ("declared: " + (s.intent or "no intent") if s else "not declared"))
    return 0


def cmd_map(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    snap, _ledger = _snapshot(args, cfg)
    print(render_map(snap, fmt=args.format))
    return 0


def cmd_features(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    snap, _ledger = _snapshot(args, cfg)
    feats = features(snap, include_merged=args.all)
    narrated = {}
    if args.llm:
        if not llm_available():
            print("no LLM configured (set MUSTER_LLM_URL); showing the deterministic digest",
                  file=sys.stderr)
        else:
            narrated = llm_narrate(feats)
    if args.json:
        out = []
        for f in feats:
            d = f.to_dict()
            if f.ref in narrated:
                d["narration"] = narrated[f.ref]
            out.append(d)
        print(json.dumps(out, indent=2))
        return 0
    if not feats:
        print("no branch carries work that %s does not already have" % snap.base)
        return 0
    for f in feats:
        print("%s  [%s]" % (f.ref, f.kind))
        if args.llm and f.ref in narrated and narrated[f.ref]["text"]:
            print("  %s" % narrated[f.ref]["text"])
        else:
            print("  %s" % f.summary)
        print("  %d ahead / %d behind %s · %d files (+%d/-%d) · %s · risk %s"
              % (f.ahead, f.behind, f.ref.split("/")[0] if "/" in f.ref else snap.base,
                 f.files_added + f.files_changed, f.lines[0], f.lines[1],
                 ("tests: yes" if f.has_tests else "tests: none"), f.risk))
        if f.docs:
            for d in f.docs[:3]:
                print("  doc: %s" % d)
        if f.risk_reasons:
            print("  why: %s" % "; ".join(f.risk_reasons))
        print("  next: %s" % f.next_action)
        if narrated.get(f.ref, {}).get("dropped"):
            print("  dropped as ungrounded: %s" % "; ".join(narrated[f.ref]["dropped"][:2]))
        print()
    return 0


def cmd_plan(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    git = Git.detect(_repo(args))
    into = args.into or cfg.get("base") or git.default_branch()
    p = merge(git, args.ref, into, apply=False, verify=cfg.get("verify") or "")
    plan = p["plan"]
    if args.json:
        print(json.dumps(plan, indent=2))
    else:
        print("plan: %s -> %s" % (args.ref, into))
        print("  verdict: %s   method: %s" % (plan["verdict"], plan.get("method") or "-"))
        print("  %d commit(s) ahead, %d behind" % (plan["ahead"], plan["behind"]))
        if plan["conflicts"]:
            print("  conflicts in %d file(s):" % len(plan["conflicts"]))
            for c in plan["conflicts"][:20]:
                print("    %s" % c)
        else:
            print("  no conflicts predicted; %d file(s) would merge automatically"
                  % len(plan["auto_merged"]))
        for n in plan["notes"]:
            print("  note: %s" % n)
        for s in plan["steps"]:
            print("  step: %s" % s)
    return 0 if plan["verdict"] != "error" else 1


def cmd_merge(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    git = Git.detect(_repo(args))
    into = args.into or cfg.get("base") or git.default_branch()
    sid, _h, _s = _session(args, git)
    res = merge(git, args.ref, into, apply=args.apply, verify=cfg.get("verify") or "",
                force=args.force, ledger=Ledger(git.toplevel()), session=sid)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        plan = res["plan"]
        print("%s -> %s : %s" % (args.ref, into, plan["verdict"]))
        for line in res["log"]:
            print("  %s" % line)
        if res.get("branch"):
            print("  branch: %s" % res["branch"])
        if not res["applied"]:
            print("  nothing was written to your working tree")
    return 0 if res["applied"] or res["plan"]["verdict"] in ("clean", "empty", "already-merged") else 1


def cmd_settle(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    git = Git.detect(_repo(args))
    snap, ledger = _snapshot(args, cfg, with_collisions=False)
    # No `or snap.base` here: settle_plan defaults to the commit the working tree
    # sits on, which is what uncommitted work is relative to.
    sp = settle_plan(git, snap, base=args.base or cfg.get("base"),
                     max_clusters=args.max)
    res = settle_apply(git, sp, apply=args.apply, ledger=ledger,
                       session=_session(args, git)[0])
    if args.json:
        print(json.dumps({"plan": [b for b in sp.branches], "result": res}, indent=2))
        return 0
    print("settle %s (base %s)" % (git.toplevel(), sp.base))
    for note in res["notes"]:
        print("  %s" % note)
    for skip in res["skipped"]:
        print("  SKIP %s" % skip)
    for b in sp.branches:
        print("\n  %s  [%s confidence]" % (b["branch"], b["confidence"]))
        print("    %s" % b["reason"])
        for p in b["paths"][:10]:
            print("      %s" % p)
        if len(b["paths"]) > 10:
            print("      ... %d more" % (len(b["paths"]) - 10))
    for c in res["created"]:
        print("\n  created %s (%d file(s)) at %s" % (c["branch"], c["files"], c["sha"]))
    for f in res["failed"]:
        print("  FAILED %s" % f)
    if not args.apply and sp.branches:
        print("\ndry run: nothing written. Re-run with --apply to create these branches.")
    return 0 if not res["failed"] else 1


def cmd_watch(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    notify = args.notify or cfg.get("notify") or ""
    state = {"n": 0}

    def show(ev, snap):
        state["n"] += 1
        line = "%s  %s" % (ev.get("at", ""), ev["kind"])
        for key in ("ref", "path", "a", "b", "level", "from", "to"):
            if key in ev:
                line += "  %s=%s" % (key, ev[key])
        print(line, flush=True)

    if not args.json:
        print("watching %s every %ds (ctrl-c to stop)" % (_repo(args) or os.getcwd(), args.interval))
    try:
        watch(repo=_repo(args), interval=args.interval, iterations=args.once,
              notify=notify, on_event=show, base=args.base or cfg.get("base"))
    except KeyboardInterrupt:
        print("\nstopped")
    if args.json:
        print(json.dumps({"events": state["n"]}))
    return 0


def cmd_init(args):
    git = Git.detect(_repo(args))
    root = git.toplevel()
    ledger = Ledger(root)
    cfg_path, created = write_default(root)
    ignored = ledger.ensure_gitignored()
    results = []
    for target in args.files:
        results.append(install_block(os.path.join(root, target), dry_run=args.dry_run))
    if args.claude_hook:
        results.append(install_claude_hook(root, dry_run=args.dry_run))
    if args.json:
        print(json.dumps({"repo": root, "config": cfg_path, "config_created": created,
                          "gitignored": ignored, "files": results}, indent=2))
        return 0
    print("initialised muster in %s" % root)
    print("  ledger: %s" % ledger.dir)
    print("  config: %s%s" % (cfg_path, " (created)" if created else " (kept existing)"))
    print("  .gitignore: %s" % ("added .muster/" if ignored else "already ignored"))
    for r in results:
        print("  %s: %s%s" % (r["path"], r["action"],
                              " (%s)" % r["error"] if not r["ok"] else ""))
    print("\nnext: muster claim --intent \"...\" --paths src/foo,tests/test_foo")
    return 0


def cmd_sync(args):
    cfg, _problems = load_config(_repo(args) or os.getcwd())
    git = Git.detect(_repo(args))
    ledger = Ledger(git.toplevel())
    if args.action == "status":
        out = syncmod.status(git, ledger)
    elif args.action == "push":
        out = syncmod.push(git, ledger, remote=args.remote, dry_run=args.dry_run)
    else:
        out = syncmod.pull(git, ledger, remote=args.remote, dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


def cmd_events(args):
    git = Git.detect(_repo(args))
    ledger = Ledger(git.toplevel())
    evs = ledger.recent_events(args.limit)
    if args.json:
        print(json.dumps(evs, indent=2))
        return 0
    if not evs:
        print("no events recorded yet")
        return 0
    for e in evs:
        detail = " ".join("%s=%s" % (k, v) for k, v in e["detail"].items()
                          if k not in ("paths",) and not isinstance(v, (dict, list)))
        print("%s  %-12s %-24s %s" % (e["ts"], e["kind"], e["session_id"] or "-", detail[:90]))
    return 0


def cmd_forget(args):
    git = Git.detect(_repo(args))
    ledger = Ledger(git.toplevel())
    if not ledger.get_session(args.session):
        print("no such session: %s" % args.session, file=sys.stderr)
        return 1
    ledger.forget(args.session)
    print("removed %s from the ledger" % args.session)
    return 0


def cmd_doctor(args):
    out = {"version": __version__}
    try:
        git = Git.detect(_repo(args))
    except GitError as exc:
        print(json.dumps({"version": __version__, "repo": None, "error": str(exc)}, indent=2)
              if args.json else "error: %s" % exc)
        return 1
    root = git.toplevel()
    cfg, problems = load_config(root)
    ver = git.version()
    from .identify import env_report
    ledger = Ledger(root)
    out.update({
        "repo": root,
        "git_version": ".".join(map(str, ver)),
        "merge_tree_fast_path": ver >= (2, 38, 0),
        "worktrees": len(git.worktrees()),
        "default_branch": git.default_branch(),
        "base": cfg.get("base") or "(auto)",
        "verify": cfg.get("verify") or "(none)",
        "config_problems": problems,
        "ledger": ledger.status(),
        "state_dir": ledger.dir,
        "state_in_repo": ledger.in_repo,
        "agent_env": [{"harness": h, "var": v, "session_id": s} for h, v, s in env_report()],
        "llm": bool(os.environ.get("MUSTER_LLM_URL")),
        "session": _session(args, git),
    })
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    for k in ("version", "repo", "git_version", "default_branch", "base", "verify",
              "merge_tree_fast_path", "worktrees", "llm"):
        print("%-22s %s" % (k, out[k]))
    print("%-22s %s" % ("ledger", out["ledger"]))
    print("%-22s %s%s" % ("state_dir", out["state_dir"],
                          "" if out["state_in_repo"] else "  (outside the repo; run `muster init` to move it in)"))
    print("%-22s %s" % ("session", "%s [%s via %s]" % out["session"]))
    if out["agent_env"]:
        print("agent harness detected:")
        for e in out["agent_env"]:
            print("  %-14s %s%s" % (e["harness"], e["var"],
                                    "  session=" + e["session_id"] if e["session_id"] else ""))
    else:
        print("agent harness detected: none (identity falls back to the process tree)")
    for p in problems:
        print("config problem: %s" % p)
    if not out["merge_tree_fast_path"]:
        print("note: git < 2.38, so conflict probes use a throwaway worktree merge")
    return 0


# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(
        prog="muster",
        description="Cross-session awareness for agents working on the same repository.",
        epilog="Start with `muster brief`, then `muster claim`, then `muster touch <path>`.",
    )
    p.add_argument("--version", action="version", version="muster " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, collisions=True):
        sp.add_argument("--repo", help="run against this repository (default: current dir)")
        sp.add_argument("--session", help="session id to act as")
        sp.add_argument("--base", help="base branch to measure lanes against")
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        if collisions:
            sp.add_argument("--local", action="store_true", help="skip remote refs")

    sp = sub.add_parser("brief", help="what other sessions are building, and what collides with you")
    common(sp)
    sp.add_argument("--format", choices=["text", "json", "md"], default="text")
    sp.add_argument("--limit", type=int, default=12)
    sp.add_argument("--no-save", action="store_true", help="do not write a snapshot")
    sp.add_argument("--no-untracked", action="store_true")
    sp.add_argument("--quiet-summary", action="store_true", help="one line, for a session hook")
    sp.set_defaults(func=cmd_brief)

    sp = sub.add_parser("scan", help="refresh the observation snapshot")
    common(sp)
    sp.add_argument("--no-untracked", action="store_true")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("claim", help="declare what you are working on")
    common(sp, collisions=False)
    sp.add_argument("--intent", help="one line: what you are building")
    sp.add_argument("--paths", action="append", help="comma-separated paths or globs you own")
    sp.add_argument("--append", action="store_true", help="add to an existing scope")
    sp.set_defaults(func=cmd_claim)

    sp = sub.add_parser("touch", help="is it safe for me to edit these paths?")
    common(sp)
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.add_argument("paths", nargs="+")
    sp.set_defaults(func=cmd_touch)

    sp = sub.add_parser("done", help="close out your session")
    common(sp, collisions=False)
    sp.add_argument("--summary", help="what you finished")
    sp.set_defaults(func=cmd_done)

    sp = sub.add_parser("whoami", help="which session id am I?")
    common(sp, collisions=False)
    sp.set_defaults(func=cmd_whoami)

    sp = sub.add_parser("map", help="full collision matrix")
    common(sp)
    sp.add_argument("--format", choices=["text", "json"], default="text")
    sp.set_defaults(func=cmd_map)

    sp = sub.add_parser("features", help="what functionality each branch carries")
    common(sp)
    sp.add_argument("--all", action="store_true", help="include branches already merged")
    sp.add_argument("--llm", action="store_true",
                    help="add narrated summaries (guarded; needs MUSTER_LLM_URL)")
    sp.set_defaults(func=cmd_features)

    sp = sub.add_parser("plan", help="what integrating a branch would do")
    common(sp, collisions=False)
    sp.add_argument("ref")
    sp.add_argument("--into", help="target branch (default: base)")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("merge", help="integrate a branch in an isolated worktree")
    common(sp, collisions=False)
    sp.add_argument("ref")
    sp.add_argument("--into")
    sp.add_argument("--apply", action="store_true", help="actually write the merge")
    sp.add_argument("--force", action="store_true", help="proceed even with conflicts")
    sp.set_defaults(func=cmd_merge)

    sp = sub.add_parser("settle", help="split a mixed working tree into reviewable lanes")
    common(sp, collisions=False)
    sp.add_argument("--apply", action="store_true", help="create the branches")
    sp.add_argument("--max", type=int, default=12, help="max lanes to propose")
    sp.set_defaults(func=cmd_settle)

    sp = sub.add_parser("watch", help="observe the repo and report when another lane moves")
    common(sp)
    sp.add_argument("--interval", type=int, default=30)
    sp.add_argument("--once", type=int, help="stop after N polls (useful in tests)")
    sp.add_argument("--notify", help="shell command to run on each event")
    sp.set_defaults(func=cmd_watch)

    sp = sub.add_parser("init", help="install agent instructions and local state")
    sp.add_argument("--repo")
    sp.add_argument("--files", nargs="+", default=["AGENTS.md"],
                    help="instruction files to update (default AGENTS.md)")
    sp.add_argument("--claude-hook", action="store_true", help="add a Claude Code SessionStart hook")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("sync", help="share the ledger across machines over a git ref")
    common(sp, collisions=False)
    sp.add_argument("action", choices=["push", "pull", "status"])
    sp.add_argument("--remote", default="origin")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("events", help="recent orchestration log")
    sp.add_argument("--repo")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_events)

    sp = sub.add_parser("forget", help="drop a session from the ledger")
    sp.add_argument("--repo")
    sp.add_argument("--session", required=True)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_forget)

    sp = sub.add_parser("doctor", help="check the environment")
    sp.add_argument("--repo")
    sp.add_argument("--session")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GitError as exc:
        print("git error: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
