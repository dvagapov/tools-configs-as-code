import sys

import pytest
import yaml

from cac.config import ConfigError
from cac.verify import verify

PY = sys.executable


def manifest(tmp_path, *steps):
    p = tmp_path / "verify.yaml"
    p.write_text(yaml.safe_dump({"schemaVersion": 1, "steps": list(steps)}))
    return p


def step(id, code="pass", expect=0, **kw):
    return {"id": id, "run": [PY, "-c", code], "expectExit": expect, **kw}


def test_all_steps_pass(tmp_path):
    out, res = verify(manifest(tmp_path, step("a"), step("b")), tmp_path)
    assert out == "pass" and all(r["passed"] for r in res)


def test_exit_mismatch(tmp_path):
    out, res = verify(manifest(tmp_path, step("a", "import sys; sys.exit(1)")), tmp_path)
    assert out == "mismatch"
    assert res[0]["reason"] == "exit_mismatch" and res[0]["exit"] == 1


def test_expected_nonzero_exit_passes(tmp_path):
    out, _ = verify(manifest(tmp_path, step("a", "import sys; sys.exit(3)", expect=3)), tmp_path)
    assert out == "pass"


def test_missing_artifact_fails_even_on_exit_zero(tmp_path):
    out, res = verify(manifest(tmp_path, step("a", artifacts=["out.json"])), tmp_path)
    assert out == "mismatch"
    assert res[0]["reason"] == "missing_artifact" and res[0]["missingArtifacts"] == ["out.json"]


def test_artifact_present_passes(tmp_path):
    code = "open('out.json','w').write('{}')"
    out, _ = verify(manifest(tmp_path, step("a", code, artifacts=["out.json"])), tmp_path)
    assert out == "pass"


def test_artifact_outside_workdir_rejected(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    out, res = verify(manifest(tmp_path, step("a", artifacts=["../secret.txt"])), work)
    assert out == "mismatch" and res[0]["missingArtifacts"] == ["../secret.txt"]


def test_timeout_fails(tmp_path):
    out, res = verify(manifest(tmp_path, step("a", "import time; time.sleep(5)", timeoutSec=1)), tmp_path)
    assert out == "mismatch" and res[0]["reason"] == "timeout"


def test_missing_binary_fails_cleanly(tmp_path):
    s = {"id": "a", "run": ["/nonexistent/bin"], "expectExit": 0}
    out, res = verify(manifest(tmp_path, s), tmp_path)
    assert out == "mismatch" and res[0]["reason"] == "launch_failed"


def test_one_failure_fails_run_but_all_steps_reported(tmp_path):
    out, res = verify(manifest(tmp_path, step("a", "import sys; sys.exit(1)"), step("b")), tmp_path)
    assert out == "mismatch" and [r["step"] for r in res] == ["a", "b"]


def test_output_hashed_not_stored(tmp_path):
    out, res = verify(manifest(tmp_path, step("a", "print('TEST_SECRET_123')")), tmp_path)
    assert res[0]["bytes"] > 0 and len(res[0]["stdoutSha256"]) == 64
    assert "TEST_SECRET_123" not in repr(res)


def test_invalid_manifests_rejected(tmp_path):
    with pytest.raises(ConfigError):
        verify(manifest(tmp_path), tmp_path)  # no steps
    with pytest.raises(ConfigError):
        verify(manifest(tmp_path, {"id": "a", "run": "npm test", "expectExit": 0}), tmp_path)  # string, not argv
    with pytest.raises(ConfigError, match="duplicate"):
        verify(manifest(tmp_path, step("a"), step("a")), tmp_path)
