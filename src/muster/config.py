
"""Optional per-repo config at .muster/config.toml.

Only a handful of keys matter. Unknown keys are reported, not ignored, so a typo
in `verify` does not silently disable the pre-merge check.
"""

from __future__ import annotations

import os

try:
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    try:
        import tomli as _toml
    except ModuleNotFoundError:
        _toml = None

DEFAULTS = {
    "base": None,                 # base branch; default = auto-detect
    "verify": "",                 # shell command run inside an isolated worktree before a merge commits
    "notify": "",                 # shell command `muster watch` calls on a new event
    "mtime_window_minutes": 45,   # edit-time proximity that suggests one task
    "stale_hours": 72,            # active session with no update for this long is stale
    "ignore": [],                 # extra globs treated as noise
    "allow_unknown_keys": False,
}

KNOWN = set(DEFAULTS)


def _mini_parse(text):
    """Fallback for Python < 3.11 without tomli: flat key = value only."""
    out = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            out[key.strip()] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
        elif val[:1] in "\"'" and val[-1:] == val[:1]:
            out[key.strip()] = val[1:-1]
        elif val.isdigit():
            out[key.strip()] = int(val)
        elif val in ("true", "false"):
            out[key.strip()] = val == "true"
        else:
            out[key.strip()] = val
    return out


def load(repo_root):
    path = os.path.join(repo_root, ".muster", "config.toml")
    cfg = dict(DEFAULTS)
    problems = []
    if os.path.exists(path):
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if _toml is not None:
                data = _toml.loads(raw.decode())
            else:
                data = _mini_parse(raw.decode())
        except Exception as exc:  # a broken config must not break the scan
            problems.append("could not parse %s: %s" % (path, exc))
            data = {}
        for key, val in data.items():
            if key in KNOWN:
                cfg[key] = val
            elif not cfg.get("allow_unknown_keys"):
                problems.append("unknown config key: %s" % key)
    return cfg, problems


def write_default(repo_root):
    path = os.path.join(repo_root, ".muster", "config.toml")
    if os.path.exists(path):
        return path, False
    body = (
        "# muster configuration. Every key is optional.\n"
        "\n"
        "# Base branch that lanes are measured against. Empty = auto-detect.\n"
        'base = ""\n'
        "\n"
        "# Run inside an isolated worktree before a merge is allowed to commit.\n"
        '# verify = "python -m pytest -q"\n'
        'verify = ""\n'
        "\n"
        "# Called by `muster watch` when something new appears. Gets the event as JSON on stdin.\n"
        'notify = ""\n'
        "\n"
        "mtime_window_minutes = 45\n"
        "stale_hours = 72\n"
        'ignore = []\n'
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)
    return path, True
