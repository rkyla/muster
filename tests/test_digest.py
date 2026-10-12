
"""The grounded digest: a branch's summary may only contain what git showed."""
import os

from muster.digest import evidence_tokens, feature_of, features, guard, llm_available
from muster.gitio import Git
from muster.observe import build_snapshot
from muster.model import RefState


def _feature(repo, name):
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    feats = {f.ref: f for f in features(snap, include_merged=True)}
    return feats[name]


def test_summary_is_built_from_commit_subjects(repo):
    f = _feature(repo, "feature/upload-api")
    assert "multipart upload endpoint" in f.summary
    assert f.ahead == 2
    assert f.evidence, "every summary needs citable evidence"
    assert any(e.startswith("commit ") for e in f.evidence)


def test_no_invented_numbers_in_summary(repo):
    f = _feature(repo, "feature/billing")
    words = f.summary.split()
    # the only numbers allowed are ones that appear in the branch's own commits
    allowed = evidence_tokens(f)
    for w in words:
        token = w.strip(".,;:()").lower()
        if token.isdigit():
            assert token in allowed


def test_added_docs_are_quoted_verbatim(repo):
    f = _feature(repo, "feature/upload-api")
    assert f.docs
    assert any("Accepts multipart posts." in d for d in f.docs)


def test_tests_present_and_absent_are_distinguished(repo):
    assert _feature(repo, "feature/upload-api").has_tests
    assert not _feature(repo, "feature/billing").has_tests
    assert any("no test files" in r for r in _feature(repo, "feature/billing").risk_reasons)


def test_merged_branch_is_not_listed_as_pending_work(repo):
    snap, _ = build_snapshot(repo=repo, window=6 * 3600)
    names = [f.ref for f in features(snap)]
    assert "chore/readme" not in names
    assert "chore/readme" in [f.ref for f in features(snap, include_merged=True)]


def test_risk_rises_for_a_branch_colliding_with_another(repo):
    f = _feature(repo, "feature/billing")
    assert f.risk == "high"
    assert any("same-region" in r for r in f.risk_reasons)


def test_next_action_names_a_real_command(repo):
    f = _feature(repo, "feature/billing")
    assert "muster plan" in f.next_action or "muster merge" in f.next_action
    assert f.ref in f.next_action


# ---- the guard ------------------------------------------------------------- #

def test_guard_rejects_invented_numbers_and_paths():
    class F:
        ref = "x"
        title = "upload api"
        summary = "adds multipart upload endpoint"
        headline_commits = ["feat(upload): multipart upload endpoint"]
        evidence = ["commit abc12345 feat(upload): multipart upload endpoint"]
        docs = []
        areas = ["app.py"]
    f = F()
    candidate = ("Adds a multipart upload endpoint in app.py. "
                 "It is 3x faster and touches 42 files. "
                 "See src/billing/stripe_webhook.py for details.")
    kept, dropped = guard(candidate, f)
    assert "multipart upload endpoint" in kept
    assert "app.py" in kept
    assert any("3x" in d or "42" in d for d in dropped)
    assert any("stripe_webhook.py" in d for d in dropped)


def test_guard_keeps_a_faithful_sentence():
    class F:
        ref = "x"
        title = "billing"
        summary = "charge() and invoice"
        headline_commits = ["feat(billing): charge() and invoice"]
        evidence = ["file A billing.py"]
        docs = []
        areas = ["billing.py"]
    kept, dropped = guard("Adds charge() and invoice in billing.py.", F())
    assert kept.strip()
    assert dropped == []


def test_llm_is_off_without_an_endpoint(monkeypatch):
    monkeypatch.delenv("MUSTER_LLM_URL", raising=False)
    assert llm_available() is False
