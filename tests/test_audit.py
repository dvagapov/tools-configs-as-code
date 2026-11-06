import json
import os
import stat
from pathlib import Path

import pytest

from cac.audit import AuditWriter
from cac.config import ConfigError, load_config
from cac.redact import redact, redact_text
from cac.workflow import run

DEFAULTS = Path(__file__).resolve().parents[1] / "framework" / "defaults.yaml"
CFG = load_config(DEFAULTS)

SECRETS = [
    "TEST_SECRET_abc123",
    "ghp_" + "a" * 36,
    "github_pat_" + "B" * 30,
    "sk-" + "c" * 24,
    "AKIA" + "D" * 16,
    "eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSMeKKF2QT4",
    "-----BEGIN PRIVATE KEY-----\nMIIabc\n-----END PRIVATE KEY-----",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_patterns_redacted(secret):
    out, n = redact_text(f"before {secret} after")
    assert secret not in out and n >= 1 and "before" in out and "after" in out


def test_assignment_and_bearer_keep_name_hide_value():
    out, n = redact_text("export GH_TOKEN=hunter2hunter2 and Authorization: Bearer abcdefghijklmnop1234")
    assert "hunter2" not in out and "abcdefghijklmnop1234" not in out
    assert "GH_TOKEN=[REDACTED]" in out and n == 2


def test_clean_text_untouched():
    assert redact_text("step unit exit 0 sha abc") == ("step unit exit 0 sha abc", 0)


def test_redact_nested_structures_and_keys():
    out, n = redact({"a": ["x TEST_SECRET_1", {"TEST_SECRET_2": 5}], "n": 3})
    assert "TEST_SECRET" not in json.dumps(out) and n == 2 and out["n"] == 3


def writer(tmp_path, cfg=CFG):
    return AuditWriter(cfg, tmp_path / "audit", "r_1")


def lines(w):
    return [json.loads(l) for l in w.path.read_text().splitlines()]


def test_planted_secret_absent_from_file_and_counted(tmp_path):
    w = writer(tmp_path)
    w.append({"event": "step_result", "step": "unit", "note": "leak TEST_SECRET_xyz here"})
    raw = w.path.read_text()
    assert "TEST_SECRET_xyz" not in raw
    rec = lines(w)[0]
    assert rec["redactions"] == 1 and w.redactions == 1
    assert rec["v"] == 1 and rec["run"] == "r_1" and "ts" in rec


def test_append_only_one_line_per_event(tmp_path):
    w = writer(tmp_path)
    w.append({"event": "a"})
    w.append({"event": "b"})
    w2 = writer(tmp_path)  # reopening never truncates
    w2.append({"event": "c"})
    assert [r["event"] for r in lines(w)] == ["a", "b", "c"]


def test_file_is_owner_only(tmp_path):
    w = writer(tmp_path)
    w.append({"event": "a"})
    assert stat.S_IMODE(os.stat(w.path).st_mode) == 0o600


@pytest.mark.parametrize("key", ["stdout", "stderr", "transcript", "env"])
def test_raw_output_keys_refused(tmp_path, key):
    w = writer(tmp_path)
    with pytest.raises(ValueError):
        w.append({"event": "x", key: "anything"})
    assert not w.path.exists()


def test_redaction_cannot_be_disabled():
    with pytest.raises(ConfigError):
        AuditWriter({"redaction": {"enabled": False}}, "/nonexistent", "r")
    with pytest.raises(ConfigError):
        AuditWriter({}, "/nonexistent", "r")


def test_manifest_redacted_with_hit_total(tmp_path):
    w = writer(tmp_path)
    w.append({"event": "a", "note": "TEST_SECRET_1"})
    p = w.write_manifest({"run": "r_1", "result": {"pr": "https://x/1 TEST_SECRET_2"}})
    text = p.read_text()
    assert "TEST_SECRET" not in text and "hits: 2" in text


def test_workflow_events_audited(tmp_path):
    ok = {**CFG["pins"], "runtime": "running"}
    script = {"plan_gate": "approved", "precommit_review": "pass", "verify_run": "pass",
              "final_review": "pass", "await_merge": "merged"}
    res = run(CFG, lambda s: script.get(s, "ok"), lambda: True, ok, lambda: ("pass", []))
    w = writer(tmp_path)
    w.extend(res.events)
    recs = lines(w)
    assert len(recs) == len(res.events) and recs[-1]["to"] == "done"
