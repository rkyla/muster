
"""Who is talking? Identity must be labelled with how it was obtained."""
import os

from muster import identify


def test_claude_code_is_detected():
    harness, sid, proof = identify.detect_harness({"CLAUDECODE": "1",
                                                   "CLAUDE_CODE_SESSION_ID": "abc-123"})
    assert harness == "claude-code"
    assert sid == "abc-123"
    assert proof == "CLAUDECODE"


def test_codex_is_detected_from_its_thread_id():
    harness, sid, _ = identify.detect_harness({"CODEX_THREAD_ID": "thr_9"})
    assert harness == "codex" and sid == "thr_9"


def test_prime_agent_is_detected():
    harness, _sid, _proof = identify.detect_harness({"RLM_SESSION_DIR": "/tmp/s"})
    assert harness == "prime-agent"


def test_a_session_id_that_is_a_path_keeps_its_last_component():
    _h, sid, _p = identify.detect_harness({"CLAUDECODE": "1",
                                           "CLAUDE_CODE_SESSION_ID": "/home/rk/.s/abc"})
    assert sid == "abc"


def test_generic_agent_var_is_a_guess_not_a_certainty():
    harness, sid, proof = identify.detect_harness({"AI_AGENT": "claude_4.5_agent"})
    assert harness and sid is None
    assert proof == "AI_AGENT"


def test_a_plain_shell_is_none_not_a_guess():
    assert identify.detect_harness({}) == (None, None, None)


def test_explicit_id_wins_and_says_so():
    sid, harness, source = identify.resolve_session(explicit="mine",
                                                    env={"CLAUDECODE": "1"})
    assert sid == "mine" and harness == "claude-code" and source == "flag"


def test_muster_session_env_is_used_and_labelled():
    sid, _h, source = identify.resolve_session(env={"MUSTER_SESSION": "lane-b"})
    assert sid == "lane-b" and source == "env:MUSTER_SESSION"


def test_harness_without_an_id_still_gets_a_distinct_session():
    sid, harness, source = identify.resolve_session(env={"CLAUDECODE": "1"})
    assert harness == "claude-code"
    assert sid.startswith("claude-code/")
    assert source == "inferred:process", "two terminals must not share one identity"


def test_ids_are_stable_for_the_same_environment():
    env = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "abc"}
    assert identify.resolve_session(env=env)[0] == identify.resolve_session(env=env)[0]


def test_ids_carry_no_spaces_no_traversal_and_no_absolute_path():
    sid, _h, _s = identify.resolve_session(explicit="  Some Tool/../Team A  ", env={})
    assert " " not in sid and ".." not in sid and not sid.startswith("/")


def test_a_namespaced_id_survives_a_round_trip():
    """`lane/b` must not read back as `lane-b`: that splits one session in two."""
    sid, _h, _s = identify.resolve_session(explicit="lane/b", env={})
    assert sid == "lane/b"


def test_a_human_shell_is_labelled_as_such(tmp_path):
    sid, harness, _source = identify.resolve_session(env={}, repo=str(tmp_path))
    assert harness == "human-or-unknown"
    assert sid.startswith("shell-")


def test_muster_current_file_is_the_last_resort_before_guessing(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), ".muster"))
    with open(os.path.join(str(tmp_path), ".muster", "CURRENT"), "w") as fh:
        fh.write("declared/one\n")
    sid, _h, source = identify.resolve_session(env={}, repo=str(tmp_path))
    assert sid == "declared/one" and source == "file:.muster/CURRENT"


def test_doctor_reports_the_signals_it_saw():
    hits = identify.env_report({"CLAUDECODE": "1", "CODEX_THREAD_ID": "t"})
    names = [h[0] for h in hits]
    assert "claude-code" in names and "codex" in names
    assert identify.env_report({}) == []


def test_every_supported_harness_has_a_probe_shape():
    for name, proof_vars, _id_vars in identify.HARNESS_SIGNALS:
        assert proof_vars, name
        assert all(v == v.upper() for v in proof_vars), name
        assert name not in ("unknown", "generic")
