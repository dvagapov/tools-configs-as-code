import copy
from pathlib import Path

import pytest

from cac.config import ConfigError, load_yaml, merge_layers

DEFAULTS = load_yaml(Path(__file__).resolve().parents[1] / "framework" / "defaults.yaml")

WORKSPACE = {
    "schemaVersion": 1,
    "workspace": "acme",
    "frameworkRef": "tools-configs-as-code@v0.1.0",
    "repos": [{"name": "fx", "url": "git@github.com:o/fx.git", "host": "github"}],
    "overrides": {"workflow.remediation.maxCycles": 3},
}
REPO = {
    "schemaVersion": 1,
    "baseBranch": "develop",
    "branchPattern": "agent/{task_id}-{slug}",
    "verification": {"manifest": ".cac/verify.yaml"},
}


def ws(**over):
    w = copy.deepcopy(WORKSPACE)
    w["overrides"] = over
    return w


def test_defaults_only():
    cfg = merge_layers(DEFAULTS)
    assert cfg["workflow"]["remediation"]["maxCycles"] == 2
    assert cfg["merge"]["byAgent"] == "forbidden"


def test_workspace_override_wins_and_repo_layer_merges():
    cfg = merge_layers(DEFAULTS, WORKSPACE, REPO)
    assert cfg["workflow"]["remediation"]["maxCycles"] == 3
    assert cfg["baseBranch"] == "develop"


def test_repo_overrides_workspace():
    repo = {**REPO, "overrides": {"workflow.remediation.maxCycles": 5}}
    assert merge_layers(DEFAULTS, WORKSPACE, repo)["workflow"]["remediation"]["maxCycles"] == 5


@pytest.mark.parametrize("key,value,locked", [
    ("merge.byAgent", "allowed", "merge.byAgent"),
    ("redaction.enabled", False, "redaction.enabled"),
    ("review.afterRemediation", "optional", "review.afterRemediation"),
    ("verification.manifestRequired", False, "verification.manifestRequired"),
    ("audit.blockOnHighSeverity", False, "audit.blockOnHighSeverity"),
    ("agentFlags.deny", {"claude": [], "codex": []}, "agentFlags.deny"),
    ("agentFlags.deny.claude", [], "agentFlags.deny"),  # error names the locked parent
])
def test_locked_override_rejected_and_named(key, value, locked):
    with pytest.raises(ConfigError, match=f"locked key '{locked}'"):
        merge_layers(DEFAULTS, ws(**{key: value}))


def test_locked_override_from_repo_layer_rejected():
    repo = {**REPO, "overrides": {"redaction.enabled": False}}
    with pytest.raises(ConfigError, match="repo-policy: locked key 'redaction.enabled'"):
        merge_layers(DEFAULTS, WORKSPACE, repo)


def test_restating_locked_value_is_allowed():
    merge_layers(DEFAULTS, ws(**{"merge.byAgent": "forbidden"}))


def test_schema_violation_reports_path():
    bad = copy.deepcopy(WORKSPACE)
    bad["repos"][0]["host"] = "svn"
    with pytest.raises(ConfigError, match="repos/0/host"):
        merge_layers(DEFAULTS, bad)


def test_unknown_workspace_key_rejected():
    with pytest.raises(ConfigError, match="surprise"):
        merge_layers(DEFAULTS, {**WORKSPACE, "surprise": 1})


def test_branch_pattern_must_be_agent_namespaced():
    with pytest.raises(ConfigError, match="branchPattern"):
        merge_layers(DEFAULTS, WORKSPACE, {**REPO, "branchPattern": "develop"})


def test_inputs_not_mutated():
    before = copy.deepcopy(DEFAULTS)
    merge_layers(DEFAULTS, WORKSPACE, REPO)
    assert DEFAULTS == before
