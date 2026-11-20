"""run_workflow: load config, run the state machine, audit the result."""
import hashlib
import json
from pathlib import Path

import yaml

from cac.audit import AuditWriter
from cac.config import ConfigError, load_config
from cac.verify import make_verify_fn
from cac.workflow import run


def _manifest_path(config, repo_dir):
    """Repo policy is untrusted input: the manifest must live inside the repo."""
    root = Path(repo_dir).resolve()
    path = (root / config["verification"]["manifest"]).resolve()
    if not path.is_relative_to(root):
        raise ConfigError(f"verification.manifest escapes the repo: {config['verification']['manifest']}")
    return path


def _resume_state(audit_dir, run_id):
    """Where a stopped run continues: a human gate it waited at, or the state whose worker or tool
    reported blocked:<reason> (a tool error, not a policy stop). Anything else restarts at intake."""
    manifest = Path(audit_dir) / f"{run_id}.manifest.yaml"
    log = Path(audit_dir) / f"{run_id}.jsonl"
    if not manifest.is_file():
        return "intake"
    final = (yaml.safe_load(manifest.read_text()) or {}).get("result", {}).get("final", "")
    if final.startswith("waiting:"):
        return final.split(":", 1)[1]
    if final.startswith("blocked:") and log.is_file():
        outcomes = [e for e in map(json.loads, log.read_text().splitlines()) if e.get("event") == "outcome"]
        if outcomes and outcomes[-1]["outcome"].startswith("blocked:"):
            return outcomes[-1]["state"]
    return "intake"


def run_workflow(defaults_path, workspace_path, repo_policy_path, repo_dir, adapter, probes, audit_dir, run_id):
    """Returns the RunResult. Raises ConfigError on invalid config before anything runs.

    `adapter(state) -> outcome` drives the agent states; `probes` are the observed
    versions and runtime status checked against the pins.
    """
    config = load_config(defaults_path, workspace_path, repo_policy_path)
    manifest = _manifest_path(config, repo_dir)
    audit = AuditWriter(config, audit_dir, run_id)

    start = _resume_state(audit_dir, run_id)
    result = run(config, adapter, manifest.is_file, probes, make_verify_fn(manifest, repo_dir), start)
    audit.extend(result.events)
    audit.write_manifest({
        "run": run_id,
        "workspace": config.get("workspace"),
        "configSha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "pins": config["pins"],
        "result": {"final": result.final},
    })
    return result
