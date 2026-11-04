"""Append-only JSONL audit writer. Every event is redacted before it touches disk.

Git history of the audit repo is the integrity record (no hash chain in the MVP).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from cac.config import ConfigError
from cac.redact import redact

FORBIDDEN_KEYS = {"stdout", "stderr", "transcript", "env", "environ"}  # never stored raw


class AuditWriter:
    def __init__(self, config, directory, run_id):
        if config.get("redaction", {}).get("enabled") is not True:
            raise ConfigError("audit requires redaction.enabled: true")
        self.run_id = run_id
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{run_id}.jsonl"
        self.redactions = 0

    def append(self, event):
        bad = FORBIDDEN_KEYS & set(event)
        if bad:
            raise ValueError(f"audit event may not carry raw {sorted(bad)}")
        clean, hits = redact(event)
        self.redactions += hits
        record = {"v": 1, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "run": self.run_id, **clean, "redactions": hits}
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

    def extend(self, events):
        for e in events:
            self.append(e)

    def write_manifest(self, manifest):
        clean, hits = redact(manifest)
        self.redactions += hits
        clean["redaction"] = {"hits": self.redactions}
        path = self.dir / f"{self.run_id}.manifest.yaml"
        path.write_text(yaml.safe_dump(clean, sort_keys=False), encoding="utf-8")
        return path
