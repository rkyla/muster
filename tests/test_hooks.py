import json

"""The instruction block agents actually read, and the hook that keeps it fresh."""
import os

from muster import hooks


def test_block_is_installed_and_marked(tmp_path):
    path = str(tmp_path / "AGENTS.md")
    out = hooks.install_block(path)
    assert out["ok"] is True
    text = open(path).read()
    assert "<!-- muster:begin -->" in text and "<!-- muster:end -->" in text
    assert "muster brief" in text


def test_installing_twice_does_not_duplicate(tmp_path):
    path = str(tmp_path / "AGENTS.md")
    hooks.install_block(path)
    first = open(path).read()
    hooks.install_block(path)
    second = open(path).read()
    assert second.count("<!-- muster:begin -->") == 1
    assert first == second


def test_existing_instructions_are_kept(tmp_path):
    path = str(tmp_path / "AGENTS.md")
    with open(path, "w") as fh:
        fh.write("# Project rules\n\nUse uv. Never force push.\n")
    hooks.install_block(path)
    text = open(path).read()
    assert "Never force push." in text
    assert "muster brief" in text
    assert text.index("Never force push.") < text.index("muster brief")


def test_an_edited_block_is_replaced_not_appended(tmp_path):
    path = str(tmp_path / "AGENTS.md")
    hooks.install_block(path)
    text = open(path).read()
    stale = text.replace("muster brief", "muster stale-command")
    with open(path, "w") as fh:
        fh.write(stale)
    hooks.install_block(path)
    after = open(path).read()
    assert "muster stale-command" not in after
    assert after.count("<!-- muster:begin -->") == 1


def test_an_unwritable_target_reports_failure_not_a_traceback(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(str(ro), 0o500)
    try:
        out = hooks.install_block(os.path.join(str(ro), "AGENTS.md"))
        assert out["ok"] is False and out["error"]
    finally:
        os.chmod(str(ro), 0o700)


def test_dry_run_touches_nothing(tmp_path):
    path = str(tmp_path / "AGENTS.md")
    out = hooks.install_block(path, dry_run=True)
    assert out["ok"] is True and out["dry_run"] is True
    assert out["action"].startswith("would")
    assert not os.path.exists(path)


def test_hints_cover_the_harnesses_without_an_agents_md():
    text = hooks.hints()
    assert "muster brief" in text
    assert len(text) < 4000, "a hint has to be short enough to be read"


def test_claude_hook_is_written_as_valid_json(tmp_path):
    out = hooks.install_claude_hook(str(tmp_path))
    assert out["ok"] is True, out
    settings = os.path.join(str(tmp_path), ".claude", "settings.json")
    data = json.load(open(settings))
    assert any("muster brief" in json.dumps(v) for v in data["hooks"].values())


def test_claude_hook_survives_being_installed_twice(tmp_path):
    hooks.install_claude_hook(str(tmp_path))
    hooks.install_claude_hook(str(tmp_path))
    data = json.load(open(os.path.join(str(tmp_path), ".claude", "settings.json")))
    assert len(data["hooks"]["SessionStart"]) == 1, "must not stack duplicate hooks"


def test_claude_hook_merges_into_existing_settings(tmp_path):
    home = tmp_path / ".claude"
    home.mkdir()
    settings = home / "settings.json"
    with open(str(settings), "w") as fh:
        json.dump({"model": "opus", "hooks": {"PreToolUse": [{"matcher": "Edit"}]}}, fh)
    hooks.install_claude_hook(str(tmp_path))
    data = json.load(open(str(settings)))
    assert data["model"] == "opus", "a user's own settings must survive"
    assert data["hooks"]["PreToolUse"] == [{"matcher": "Edit"}]
    assert data["hooks"]["SessionStart"]


def test_unparseable_settings_are_refused_not_replaced(tmp_path):
    home = tmp_path / ".claude"
    home.mkdir()
    with open(str(home / "settings.json"), "w") as fh:
        fh.write("{not json")
    out = hooks.install_claude_hook(str(tmp_path))
    assert out["ok"] is False
    assert "unparseable" in out["error"]
    assert open(str(home / "settings.json")).read() == "{not json"
