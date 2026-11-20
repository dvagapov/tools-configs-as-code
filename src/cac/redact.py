"""Secret redaction for audit data. Best-effort pattern matching, not a guarantee."""
import re

PATTERNS = {
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "api_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    "aws_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    "bearer": re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"),
    "assignment": re.compile(
        r"(?i)\b([A-Za-z0-9_]*(?:token|secret|password|passwd|api_?key)[A-Za-z0-9_]*)(\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s\"',;]+)"),
    "test_secret": re.compile(r"\bTEST_SECRET_[A-Za-z0-9_]+\b"),
}
MARK = "[REDACTED]"


def redact_text(text):
    """Return (redacted_text, hit_count)."""
    hits = 0
    for name, rx in PATTERNS.items():
        if name == "assignment":
            text, n = rx.subn(lambda m: f"{m.group(1)}{m.group(2)}{MARK}", text)
        elif name == "bearer":
            text, n = rx.subn(lambda m: f"{m.group(1)} {MARK}", text)
        else:
            text, n = rx.subn(MARK, text)
        hits += n
    return text, hits


def redact(value):
    """Recursively redact strings in dicts/lists (keys too). Returns (value, hits)."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out, total = {}, 0
        for k, v in value.items():
            k2, hk = redact_text(str(k))
            v2, hv = redact(v)
            out[k2] = v2
            total += hk + hv
        return out, total
    if isinstance(value, (list, tuple)):
        items = [redact(v) for v in value]
        return [v for v, _ in items], sum(h for _, h in items)
    return value, 0
