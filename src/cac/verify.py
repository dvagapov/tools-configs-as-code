"""Verification runner: manifest -> exit codes and artifacts.

The wrapper, not the agent, decides pass/fail. Only a hash and byte count of
the output are kept (never the output itself).
"""
import hashlib
import subprocess
from pathlib import Path

from cac.config import ConfigError, load_yaml, validate

DEFAULT_TIMEOUT = 600


def load_manifest(path):
    data = load_yaml(path)
    validate("verify", data, str(path))
    ids = [s["id"] for s in data["steps"]]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{path}: duplicate step id")
    return data


def _artifact_ok(root, rel):
    p = (root / rel).resolve()
    return p.is_relative_to(root) and p.exists()


def run_step(step, cwd):
    root = Path(cwd).resolve()
    res = {"step": step["id"], "expected": step["expectExit"], "exit": None,
           "missingArtifacts": [], "stdoutSha256": None, "bytes": 0, "reason": None}
    try:
        p = subprocess.run(step["run"], cwd=root, capture_output=True,
                           timeout=step.get("timeoutSec", DEFAULT_TIMEOUT))
    except subprocess.TimeoutExpired:
        res["reason"] = "timeout"
        return {**res, "passed": False}
    except OSError:
        res["reason"] = "launch_failed"
        return {**res, "passed": False}
    out = p.stdout + p.stderr
    res.update(exit=p.returncode, stdoutSha256=hashlib.sha256(out).hexdigest(), bytes=len(out))
    res["missingArtifacts"] = [a for a in step.get("artifacts", []) if not _artifact_ok(root, a)]
    if p.returncode != step["expectExit"]:
        res["reason"] = "exit_mismatch"
    elif res["missingArtifacts"]:
        res["reason"] = "missing_artifact"
    return {**res, "passed": res["reason"] is None}


def verify(manifest_path, cwd):
    """Run every step (no short-circuit, so one report shows all failures).

    Returns ("pass" | "mismatch", results). Raises ConfigError on an invalid manifest.
    """
    manifest = load_manifest(manifest_path)
    results = [run_step(s, cwd) for s in manifest["steps"]]
    return ("pass" if all(r["passed"] for r in results) else "mismatch"), results
