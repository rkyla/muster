
"""Turn refs into a grounded description of the functionality they carry.

Hard rule: every sentence in a feature summary must trace to something git
showed us - a commit subject, a changed path, or a heading inside a document the
branch added. The summariser may reorder and compress facts; it may not add one.
`guard()` enforces that on any LLM-written text by rejecting identifiers that do
not appear in the evidence set.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .gitio import Git
from .model import RefState

CONVENTIONAL = re.compile(r"^([a-z]+)(\([^)]*\))?(!)?:\s*(.+)$")
TYPE_WORDS = {
    "feat": "adds", "fix": "fixes", "docs": "documents", "test": "tests",
    "refactor": "refactors", "perf": "speeds up", "build": "changes the build for",
    "ci": "changes CI for", "chore": "does maintenance on", "style": "restyles",
    "security": "hardens",
}
STOPWORDS = {"the", "and", "for", "with", "from", "into", "that", "this", "work",
             "changes", "update", "adds", "fixes", "v1", "v2", "wip", "more", "some"}


@dataclass
class Feature:
    ref: str
    kind: str
    title: str
    summary: str
    areas: list[str] = field(default_factory=list)
    headline_commits: list[str] = field(default_factory=list)
    docs: list[str] = field(default_factory=list)
    tests_touched: list[str] = field(default_factory=list)
    has_tests: bool = False
    files_added: int = 0
    files_changed: int = 0
    lines: tuple = (0, 0)
    last_activity: str = ""
    days_stale: float = -1.0
    ahead: int = 0
    behind: int = 0
    merged: bool = False
    risk: str = "unknown"
    risk_reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    next_action: str = ""

    def to_dict(self):
        d = self.__dict__.copy()
        d["lines"] = list(self.lines)
        return d


# --------------------------------------------------------------------------- #

def _branch_words(name):
    name = name.split("/")[-1]
    out = []
    for w in re.split(r"[-_/.\s]+", name):
        if len(w) > 2 and w.lower() not in STOPWORDS:
            out.append(w.lower())
    return out


def _clean_subject(subject):
    m = CONVENTIONAL.match(subject or "")
    if m:
        return m.group(4).strip()
    return (subject or "").strip()


def _doc_headings(git: Git, ref: RefState, paths, limit=4):
    """Lines this branch actually wrote into added docs, quoted verbatim.

    These are the most useful and most hallucinatable part of a summary, so they
    are copied out of the blob rather than paraphrased: a heading plus the first
    real sentence, per added document.
    """
    found = []
    for path in paths:
        if not path.endswith((".md", ".rst", ".txt")):
            continue
        text = git.show(ref.sha, path) or ""
        picked = []
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith(("|", "```", ">")):
                continue
            if s.startswith("#"):
                picked.append(s.lstrip("# ").strip()[:110])
            elif len(s) > 12 and not s.startswith(("-", "*", "+")):
                picked.append(s[:110])
            if len(picked) >= 2:
                break
        for line in picked:
            found.append("%s: %s" % (os.path.basename(path), line))
        if len(found) >= limit:
            break
    return found[:limit]


def _days_since(iso, now=None):
    import time
    if not iso:
        return -1.0
    try:
        then = time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return -1.0
    return round(((now or time.time()) - then) / 86400.0, 1)


def _title(ref: RefState, commits):
    words = _branch_words(ref.name)
    if words:
        return " ".join(words[:6])
    if commits:
        return _clean_subject(commits[0]["subject"])[:60]
    return ref.name


_LEADING_VERBS = {
    "add", "adds", "allow", "allows", "clean", "cleans", "drop", "drops", "fix", "fixes",
    "handle", "handles", "implement", "implements", "improve", "improves", "introduce",
    "introduces", "keep", "keeps", "label", "labels", "make", "makes", "migrate",
    "migrates", "refactor", "refactors", "remove", "removes", "rename", "renames",
    "repair", "repairs", "replace", "replaces", "route", "routes", "set", "sets",
    "split", "splits", "support", "supports", "update", "updates", "use", "uses",
    "wire", "wires", "write", "writes", "document", "documents", "fall", "falls",
}


def _summary(ref: RefState, commits, docs, areas):
    """Assemble from commit subjects only. No invented connective prose."""
    if not commits:
        if ref.merged_into_base:
            return "Already contained in %s; nothing left to integrate." % ref.base
        return "No commits ahead of %s; branch is a pointer only." % ref.base
    verbs = []
    for c in commits[:6]:
        subj = c["subject"]
        m = CONVENTIONAL.match(subj)
        body = _clean_subject(subj)
        if not body:
            continue
        verbs.append((TYPE_WORDS.get(m.group(1), "") if m else "", body))
    parts = []
    for verb, body in verbs[:4]:
        body = body.rstrip(".")
        first = body.split(" ")[0].lower() if body else ""
        # "repair bad replies in the same conversation" is already a sentence with
        # a verb; prefixing it with "adds" produces "adds repair bad replies".
        if first in _LEADING_VERBS or not verb:
            parts.append(body)
        else:
            parts.append("%s %s" % (verb, body))
    parts = [t[0].upper() + t[1:] if t else t for t in parts]
    line = "; ".join(parts)
    if len(verbs) > 4:
        line += "; and %d more commit%s" % (len(verbs) - 4, "" if len(verbs) == 5 else "s")
    if docs:
        line += ". Documents %s" % ", ".join(sorted({os.path.basename(d.split(":")[0]) for d in docs}))
    return line[:600]


def _risk(ref: RefState, snap, collisions, days=-1.0):
    reasons, level = [], "low"
    mine = [c for c in collisions if c.path in {f.path for f in ref.files}
            and (c.a == ref.name or c.b == ref.name)]
    high = [c for c in mine if c.severity == "high"]
    med = [c for c in mine if c.severity == "medium"]
    if high:
        level = "high"
        reasons.append("%d same-region edit%s with other work" % (
            len(high), "" if len(high) == 1 else "s"))
    elif med:
        level = "medium"
        reasons.append("%d shared-file edit%s" % (len(med), "" if len(med) == 1 else "s"))
    if ref.behind > 20:
        if level == "low":
            level = "medium"
        reasons.append("%d commits behind %s" % (ref.behind, ref.base))
    if days > 21 and level == "low":
        level = "medium"
        reasons.append("untouched for %.0f days" % days)
    if not any(f.path.startswith(("tests/", "test")) or f.path.endswith(("_test.py", ".test.js", ".test.jsx"))
               for f in ref.files):
        reasons.append("no test files in the diff")
    if ref.merged_into_base:
        level = "low"
        reasons.append("already merged into %s" % ref.base)
    return level, reasons


def _next_action(feat: Feature):
    if feat.merged:
        return "safe to delete the branch, or keep as history"
    if feat.ahead == 0:
        return "no commits ahead of %s; nothing to integrate" % feat.ref
    if feat.risk == "high":
        return "run `muster plan %s` before editing the shared files" % feat.ref
    if feat.behind > 20:
        return "rebase or merge %s in first: %d commits behind" % (feat.ref, feat.behind)
    if not feat.has_tests:
        return "integrate with `muster merge %s --dry-run`; add tests, none in the diff" % feat.ref
    return "integrate with `muster merge %s --dry-run`" % feat.ref


def feature_of(ref: RefState, snap, git: Git | None = None) -> Feature:
    git = git or Git(snap.repo)
    commits = ref.commits
    added = [f for f in ref.files if f.status in ("A", "R")]
    changed = [f for f in ref.files if f.status not in ("A",)]
    docs = _doc_headings(git, ref, [f.path for f in added])
    tests = [f.path for f in ref.files
             if f.path.startswith(("tests/", "test")) or f.path.endswith(
                 ("_test.py", "test_.py", ".test.js", ".test.jsx", ".test.ts", ".spec.js"))]
    areas = sorted({f.path.split("/")[0] for f in ref.files})[:8]
    add = sum(f.lines_added for f in ref.files if f.lines_added > 0)
    dele = sum(f.lines_deleted for f in ref.files if f.lines_deleted > 0)
    days = _days_since(ref.committer_date)
    feat = Feature(
        ref=ref.name, kind=ref.kind, title=_title(ref, commits),
        summary=_summary(ref, commits, docs, areas), areas=areas,
        headline_commits=[_clean_subject(c["subject"]) for c in commits[:6]],
        docs=docs, tests_touched=tests[:8], has_tests=bool(tests),
        files_added=len(added), files_changed=len(changed), lines=(add, dele),
        last_activity=ref.committer_date, days_stale=days,
        ahead=ref.ahead, behind=ref.behind, merged=ref.merged_into_base,
        evidence=["commit %s %s" % (c["sha"][:8], c["subject"][:70]) for c in commits[:8]]
                 + ["file %s %s" % (f.status, f.path) for f in ref.files[:12]],
    )
    if ref.ahead == 0:
        # Nothing pending: say so instead of inventing a feature description.
        feat.summary = "Already merged into %s; nothing left to integrate." % (ref.base or "the base")
        feat.docs = []
        feat.evidence = ["ref %s at %s" % (ref.name, ref.sha[:8]),
                         "merge-base with %s is the branch tip" % (ref.base or "the base")]
    feat.risk, feat.risk_reasons = _risk(ref, snap, snap.collisions, days=days)
    feat.next_action = _next_action(feat)
    return feat


def features(snap, include_merged=False, limit=40):
    git = Git(snap.repo)
    out = []
    for ref in snap.refs:
        if ref.is_base:
            continue
        if (ref.merged_into_base or ref.ahead == 0) and not include_merged:
            continue
        if ref.ahead == 0 and not include_merged:
            continue
        out.append(feature_of(ref, snap, git))
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# optional LLM narration, with a grounding guard
# --------------------------------------------------------------------------- #

def evidence_tokens(feature: Feature):
    """Identifiers the model is allowed to use. Anything else is a fabrication."""
    text = " ".join([feature.title, feature.summary] + feature.headline_commits
                    + feature.evidence + feature.docs + feature.areas)
    toks = set()
    for pat in (r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+", r"\b[0-9a-f]{7,40}\b", r"\b\d+\b"):
        for m in re.finditer(pat, text):
            toks.add(m.group(0).lower())
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text.lower()):
        if w not in STOPWORDS:
            toks.add(w)
    return toks


_NUM_RX = re.compile(r"\b\d[\d.,]*\b")


def guard(candidate: str, feature: Feature):
    """Return (kept_text, rejected_sentences).

    A sentence survives only if every path-like token, sha, and number in it was
    observed. This is what stops a friendly model from upgrading "some commits"
    into "12 commits, 3x faster".
    """
    allowed = evidence_tokens(feature)
    kept, rejected = [], []
    for sentence in re.split(r"(?<=[.!?])\s+", candidate.strip()):
        s = sentence.strip()
        if not s:
            continue
        bad = []
        for tok in re.findall(r"[A-Za-z0-9_./-]+\.[A-Za-z0-9]+", s):
            if tok.lower() not in allowed:
                bad.append(tok)
        for tok in re.findall(r"\b[0-9a-f]{7,40}\b", s):
            if tok.lower() not in allowed:
                bad.append(tok)
        for tok in _NUM_RX.findall(s):
            if tok.strip(".,").lower() not in allowed:
                bad.append(tok)
        (rejected if bad else kept).append((s, bad))
    return " ".join(s for s, _ in kept), [s for s, bad in rejected if True]


def llm_available():
    return bool(os.environ.get("MUSTER_LLM_URL"))


def llm_narrate(features, timeout=45):
    """Optional narrative pass. Returns {} when no endpoint is configured.

    Reads MUSTER_LLM_URL / MUSTER_LLM_MODEL / MUSTER_LLM_KEY. Output is passed
    through guard() before it is returned, so the caller never sees ungated text.
    """
    if not llm_available() or not features:
        return {}
    url = os.environ["MUSTER_LLM_URL"].rstrip("/") + "/chat/completions"
    model = os.environ.get("MUSTER_LLM_MODEL", "gpt-4o-mini")
    out = {}
    for f in features:
        prompt = (
            "Rewrite this feature summary as two plain sentences for an engineer "
            "joining the repo. Use ONLY the facts given. Do not add numbers, "
            "paths, or claims that are not in the facts.\n\nFACTS:\n%s\n" % (
                "\n".join(["- " + e for e in f.evidence[:10]] + ["- " + c for c in f.headline_commits[:6]]))
        )
        body = json.dumps({"model": model, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            **({"Authorization": "Bearer " + os.environ["MUSTER_LLM_KEY"]}
               if os.environ.get("MUSTER_LLM_KEY") else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            raw = data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError) as exc:
            f.risk_reasons.append("llm narration skipped: %s" % type(exc).__name__)
            continue
        kept, dropped = guard(raw, f)
        out[f.ref] = {"text": kept, "dropped": dropped}
    return out
