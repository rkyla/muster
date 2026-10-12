
"""Agent-facing integration: the instructions and hooks that make agents use this.

A tool nobody calls is worth nothing, so `muster init` writes the rules into the
files agents already read (AGENTS.md, CLAUDE.md) and can install a session-start
hook. The block is delimited by markers so it is updated in place and never
duplicated.
"""

from __future__ import annotations

import json
import os

BEGIN = "<!-- muster:begin -->"
END = "<!-- muster:end -->"

BLOCK = """{begin}
## Cross-session awareness (muster)

Other agent sessions may be working in this repository at the same time as you -
on other branches, other worktrees, or in this exact working tree. You cannot see
them by looking at `git status`. Use `muster`:

1. `muster brief` - what other lanes are building, what they have uncommitted, what collides with you.
2. `muster claim --intent "<what you are doing>" --paths <dir1>,<dir2>` - declare your scope at the start.
3. `muster touch <path>` - safe / caution / stop verdict before you edit a file.
4. `muster done --summary "<outcome>"` - close out when you finish.

Hard rules for a shared working tree:

- Do not revert, reformat, or "clean up" a file you did not change. Uncommitted
  changes here may belong to another session.
- Never run `git reset --hard`, `git checkout .`, `git clean -fd`, or `git stash`
  without reading `muster brief` first. Those commands destroy other lanes' work.
- If `muster touch` says STOP, read `muster map`, then integrate with
  `muster plan <branch>` instead of editing over the top of it.
- Commit your own scope only (`git add <your paths>`), never `git add -A`.
{end}""".format(begin=BEGIN, end=END)


def _splice(text, block):
    """Replace the marker-delimited block, or append it. Idempotent."""
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        _old, post = rest.split(END, 1)
        return pre + block + post
    if not text:
        return block + "\n"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block + "\n"


def install_block(path, dry_run=False):
    existed = os.path.exists(path)
    try:
        text = open(path).read() if existed else ""
    except OSError as exc:
        return {"path": path, "ok": False, "error": str(exc)}
    if BEGIN in text and END in text:
        updated = _splice(text, BLOCK)
        action = "updated" if updated != text else "unchanged"
    else:
        updated = _splice(text, BLOCK)
        action = "appended"
    if dry_run:
        return {"path": path, "ok": True, "action": "would " + action, "existed": existed,
                "dry_run": True}
    if action == "unchanged":
        return {"path": path, "ok": True, "action": action, "existed": existed}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            fh.write(updated)
    except OSError as exc:
        # A read-only checkout or a missing parent dir is a reportable outcome,
        # not a traceback in the middle of `muster init`.
        return {"path": path, "ok": False, "error": str(exc)}
    return {"path": path, "ok": True, "action": action, "existed": existed,
            "dry_run": False}


CLAUDE_HOOK = {
    "type": "command",
    "command": 'muster brief --quiet-summary 2>/dev/null || echo "muster not installed: pipx install muster-cli"',
}


def install_claude_hook(repo, dry_run=False):
    """Add a SessionStart hook to .claude/settings.json without clobbering it."""
    path = os.path.join(repo, ".claude", "settings.json")
    data = {}
    if os.path.exists(path):
        try:
            data = json.load(open(path))
        except ValueError as exc:
            return {"path": path, "ok": False, "error": "refusing to overwrite unparseable JSON: %s" % exc}
    hooks = data.setdefault("hooks", {})
    starts = hooks.setdefault("SessionStart", [])
    for entry in starts:
        for h in entry.get("hooks", []):
            if "muster" in h.get("command", ""):
                return {"path": path, "ok": True, "action": "unchanged"}
    entry = {"matcher": "startup", "hooks": [dict(CLAUDE_HOOK)]}
    if dry_run:
        return {"path": path, "ok": True, "action": "would add SessionStart hook"}
    starts.append(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    return {"path": path, "ok": True, "action": "added SessionStart hook"}


OPENCODE_HINT = """# opencode
Add to .opencode/opencode.json (or the global config) so sessions start informed:

  "instructions": ["AGENTS.md"]

opencode reads AGENTS.md, which `muster init` already updated. No extra hook needed.
"""

CODEX_HINT = """# Codex CLI
Codex reads AGENTS.md, which `muster init` already updated. To also run a brief on
every turn, add to .codex/config.toml:

  [hooks]
  session_start = "muster brief --quiet-summary"
"""


def hints():
    return OPENCODE_HINT.strip() + "\n\n" + CODEX_HINT.strip()
