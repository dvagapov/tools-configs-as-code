"""run_workflow: load config, run the state machine, audit the result."""
import hashlib
import json
from pathlib import Path

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


def run_workflow(defaults_path, workspace_path, repo_policy_path, repo_dir, adapter, probes, audit_dir, run_id):
    """Returns the RunResult. Raises ConfigError on invalid config before anything runs.

    `adapter(state) -> outcome` drives the agent states; `probes` are the observed
    versions and runtime status checked against the pins.
    """
    config = load_config(defaults_path, workspace_path, repo_policy_path)
    manifest = _manifest_path(config, repo_dir)
    audit = AuditWriter(config, audit_dir, run_id)

    result = run(config, adapter, manifest.is_file, probes, make_verify_fn(manifest, repo_dir))
    audit.extend(result.events)
    audit.write_manifest({
        "run": run_id,
        "workspace": config.get("workspace"),
        "configSha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "pins": config["pins"],
        "result": {"final": result.final},
    })
    return result
