import json
from pathlib import Path

import pytest

from cac.config import ConfigError, load_config
from cac.render import denied_flags, load_profiles, render, render_codex, render_claude

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config(ROOT / "framework" / "defaults.yaml")
PROFILES = load_profiles()


def test_shipped_profiles_all_render(tmp_path):
    for name in PROFILES:
        argv, files = render(name, PROFILES, CFG, tmp_path)
        assert argv[0] in ("claude", "codex")
        assert denied_flags(argv, sum(CFG["locked"]["agentFlags.deny"].values(), [])) == []


def test_planner_argv_and_no_settings_body(tmp_path):
    argv, files = render("planner", PROFILES, CFG, tmp_path)
    assert argv == ["claude", "--model", "opus", "--effort", "high", "--permission-mode", "plan",
                    "--settings", str(tmp_path / "planner.settings.json")]
    assert json.loads(files[str(tmp_path / "planner.settings.json")]) == {}


def test_implementer_allowed_tools_in_settings(tmp_path):
    _, files = render("implementer", PROFILES, CFG, tmp_path)
    settings = json.loads(next(iter(files.values())))
    assert settings["permissions"]["allow"] == PROFILES["implementer"]["allowedTools"]


def test_codex_reviewer_argv_null_model_omitted(tmp_path):
    argv, files = render("reviewer", PROFILES, CFG, tmp_path)
    assert argv == ["codex", "-c", 'model_reasoning_effort="high"', "-s", "read-only"]
    assert files == {}


def test_allowed_commands_not_rendered(tmp_path):
    argv, _ = render("git-ops", PROFILES, CFG, tmp_path)
    assert "gh pr create" not in " ".join(argv)


@pytest.mark.parametrize("profile", [
    {"agent": "claude", "permissionMode": "bypassPermissions"},
    {"agent": "codex", "sandbox": "danger-full-access"},
])
def test_deny_listed_profile_fails_to_render(profile, tmp_path):
    with pytest.raises(ConfigError, match="deny-listed"):
        render("x", {"x": profile}, CFG, tmp_path)


def test_denied_flags_spellings():
    deny = ["--sandbox=danger-full-access", "--dangerously-bypass-approvals-and-sandbox",
            "--permission-mode=bypassPermissions"]
    assert denied_flags(["codex", "-s", "danger-full-access"], deny) == [deny[0]]
    assert denied_flags(["codex", "--sandbox=danger-full-access"], deny) == [deny[0]]
    assert denied_flags(["codex", "--dangerously-bypass-approvals-and-sandbox"], deny) == [deny[1]]
    assert denied_flags(["claude", "--permission-mode", "bypassPermissions"], deny) == [deny[2]]
    assert denied_flags(["codex", "-s", "read-only"], deny) == []


def test_unknown_profile(tmp_path):
    with pytest.raises(ConfigError, match="unknown"):
        render("nope", PROFILES, CFG, tmp_path)


def test_schema_rejects_cross_agent_keys(tmp_path):
    import yaml
    from cac.config import validate
    bad = [{"agent": "claude", "sandbox": "read-only"}, {"agent": "codex", "permissionMode": "plan"},
           {"agent": "claude", "effort": "turbo"}, {"agent": "gemini"}]
    for p in bad:
        with pytest.raises(ConfigError):
            validate("profiles", {"schemaVersion": 1, "profiles": {"x": p}}, "t")
