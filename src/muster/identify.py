
"""Session identity: who is talking to this repository right now.

Agents rarely pass an explicit id, so identity is resolved from the harness
environment when possible. Every guess is labelled with its source so a brief can
say "inferred" instead of pretending to know.
"""

from __future__ import annotations

import hashlib
import os
import re

# Ordered: first match wins. (harness, env var that proves it, env var holding a session id)
HARNESS_SIGNALS = [
    ("claude-code",  ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"], ["CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION"]),
    ("codex",        ["CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_CI", "CODEX_THREAD_ID"], ["CODEX_THREAD_ID"]),
    ("gemini-cli",   ["GEMINI_CLI"], ["GEMINI_CLI_SESSION_ID"]),
    ("copilot-cli",  ["COPILOT_CLI", "COPILOT_AGENT_SESSION_ID"], ["COPILOT_AGENT_SESSION_ID"]),
    ("cursor",       ["CURSOR_TRACE_ID", "CURSOR_EXTENSION_HOST_ROLE", "CURSOR_WORKSPACE_LABEL"], ["CURSOR_TRACE_ID"]),
    ("windsurf",     ["WINDSURF_SESSION_ID", "CODEIUM_SESSION_ID"], ["WINDSURF_SESSION_ID", "CODEIUM_SESSION_ID"]),
    ("opencode",     ["OPENCODE_CONFIG", "OPENCODE_SESSION_ID"], ["OPENCODE_SESSION_ID"]),
    ("aider",        ["AIDER_EDIT", "AIDER_ORIGINAL_CWD"], ["AIDER_ANALYTRY_ID_COLLECTION_PATH"]),
    ("openhands",    ["OPENHANDS_RUNTIME", "OPENHANDS_WORKSPACE"], ["OPENHANDS_RUNTIME_ID"]),
    ("amp",          ["AMP_THREAD_ID", "AMP_API_KEY"], ["AMP_THREAD_ID"]),
    ("goose",        ["GOOSE_PROVIDER", "GOOSE_SESSION"], ["GOOSE_SESSION"]),
    ("devin",        ["DEVIN_SESSION_ID", "DEVIN_MACHINE_ID"], ["DEVIN_SESSION_ID"]),
    ("prime-agent",  ["PI_CODING_AGENT", "PRIME_AGENT_CODING_AGENT_DIR", "RLM_SESSION_DIR"],
                     ["PRIME_AGENT_INTERNAL_DAEMON_WORKER_ACTIVE_SESSION_ID", "RLM_SESSION_ID"]),
]

GENERIC_AGENT_VARS = ["AI_AGENT", "AGENT_SDK", "CLAUDE_AGENT_SDK_VERSION"]


def _short(value, n=12):
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value)).strip("-")
    return value[:n] or "x"


def _short_id(value, n=48):
    """Sanitise a session id without destroying its namespace.

    Ids are `harness/id`, so "/" is meaningful and must survive: a CURRENT file
    holding `lane/b` that reads back as `lane-b` splits one session into two.
    Whitespace, control characters, ".." and a leading "/" are still removed.
    """
    value = re.sub(r"[^A-Za-z0-9._/-]+", "-", str(value).strip()).strip("-/.")
    value = "/".join(p for p in value.split("/") if p and p != "..")
    return value[:n] or "x"


def detect_harness(env=None):
    """Return (harness, session_id|None, evidence) from the environment."""
    env = os.environ if env is None else env
    for name, proof_vars, id_vars in HARNESS_SIGNALS:
        proof = next((v for v in proof_vars if env.get(v)), None)
        if not proof:
            continue
        sid = next((env[v] for v in id_vars if env.get(v)), None)
        if sid and sid.endswith("/"):
            sid = sid.rstrip("/").rsplit("/", 1)[-1]
        if sid and "/" in sid:
            sid = sid.rsplit("/", 1)[-1]
        return name, (sid or None), proof
    generic = next((v for v in GENERIC_AGENT_VARS if env.get(v)), None)
    if generic:
        val = env[generic]
        guess = _short(val.split("_")[0].lower(), 20)
        return guess, None, generic
    return None, None, None


def _pid_fallback(env):
    """Stable-ish id for a plain shell session: the controlling process tree."""
    try:
        ppid = os.getppid()
        with open("/proc/%d/stat" % ppid) as fh:
            fields = fh.read().rsplit(")", 1)[-1].split()
        start_ticks = fields[19] if len(fields) > 19 else "0"
        tty = fields[6] if len(fields) > 6 else "0"
    except Exception:
        ppid, start_ticks, tty = os.getppid(), "0", "0"
    raw = "%s:%s:%s" % (ppid, start_ticks, tty)
    return "shell-" + hashlib.sha1(raw.encode()).hexdigest()[:10]


def resolve_session(explicit=None, env=None, repo=None):
    """Resolve the acting session id. Returns (session_id, harness, source)."""
    env = os.environ if env is None else env
    if explicit:
        harness = detect_harness(env)[0] or "explicit"
        return _short_id(explicit), harness, "flag"
    if env.get("MUSTER_SESSION"):
        harness = detect_harness(env)[0] or "env"
        return _short_id(env["MUSTER_SESSION"]), harness, "env:MUSTER_SESSION"
    harness, sid, _proof = detect_harness(env)
    if harness and sid:
        return "%s/%s" % (harness, _short(sid)), harness, "env:harness"
    if harness:
        # Harness known but it exposes no session id: derive one from the process
        # tree so two terminals running the same harness stay distinct.
        return "%s/%s" % (harness, _short(_pid_fallback(env).split("-", 1)[1], 16)), harness, "inferred:process"
    if repo:
        cur = os.path.join(repo, ".muster", "CURRENT")
        if os.path.exists(cur):
            try:
                with open(cur) as fh:
                    val = fh.read().strip()
                if val:
                    return _short_id(val), "unknown", "file:.muster/CURRENT"
            except OSError:
                pass
    return _pid_fallback(env), "human-or-unknown", "inferred:process"


def env_report(env=None):
    """For `muster doctor`: which agent-harness signals are visible right now."""
    env = os.environ if env is None else env
    hits = []
    for name, proof_vars, id_vars in HARNESS_SIGNALS:
        for v in proof_vars:
            if env.get(v):
                hits.append((name, v, env.get(id_vars[0]) if id_vars and env.get(id_vars[0]) else None))
                break
    for v in GENERIC_AGENT_VARS:
        if env.get(v):
            hits.append(("generic", v, env[v][:40]))
    return hits
