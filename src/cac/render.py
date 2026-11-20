"""Render agent profiles into launch argv and agent config files.

Output is generated from the merged config; deny-listed flags (locked
`agentFlags.deny`) are checked against the final argv, so a profile that would
produce one fails to render instead of being launched.
"""
import json
from pathlib import Path

from cac.config import ConfigError, load_yaml, validate

PROFILES_PATH = Path(__file__).resolve().parents[2] / "framework" / "agents" / "profiles.yaml"
ALIASES = {"-s": "--sandbox"}


def load_profiles(path=PROFILES_PATH):
    data = load_yaml(path)
    validate("profiles", data, str(path))
    return data["profiles"]


def denied_flags(argv, deny):
    """Return deny entries matched by argv, in `--flag` or `--flag=value` form,
    for both `--flag value` and `--flag=value` spellings (and short aliases)."""
    toks = [ALIASES.get(t, t) for t in argv]
    seen = set(toks)
    for i, t in enumerate(toks[:-1]):
        if t.startswith("-") and "=" not in t:
            seen.add(f"{t}={toks[i + 1]}")
    return [d for d in deny if d in seen]


def _check(argv, agent, config):
    hit = denied_flags(argv, config["locked"]["agentFlags.deny"][agent])
    if hit:
        raise ConfigError(f"profile renders deny-listed flag(s) {hit}")


def render_claude(name, profile, config, settings_path):
    """Return (argv, settings_dict). The caller writes settings_dict to settings_path."""
    argv = ["claude"]
    if profile.get("model"):
        argv += ["--model", profile["model"]]
    if profile.get("effort"):
        argv += ["--effort", profile["effort"]]
    if profile.get("permissionMode"):
        argv += ["--permission-mode", profile["permissionMode"]]
    argv += ["--settings", str(settings_path)]
    settings = {}
    if profile.get("allowedTools"):
        settings["permissions"] = {"allow": list(profile["allowedTools"])}
    _check(argv, "claude", config)
    return argv, settings


def render_codex(name, profile, config):
    argv = ["codex"]
    if profile.get("model"):
        argv += ["-m", profile["model"]]
    if profile.get("effort"):
        argv += ["-c", f'model_reasoning_effort="{profile["effort"]}"']
    if profile.get("sandbox"):
        argv += ["-s", profile["sandbox"]]
    _check(argv, "codex", config)
    return argv


def render(name, profiles, config, settings_dir):
    """Render one profile. Returns (argv, files) where files maps path -> text."""
    if name not in profiles:
        raise ConfigError(f"unknown profile '{name}'")
    p = profiles[name]
    if p["agent"] == "claude":
        path = Path(settings_dir) / f"{name}.settings.json"
        argv, settings = render_claude(name, p, config, path)
        return argv, {str(path): json.dumps(settings, indent=2) + "\n"}
    return render_codex(name, p, config), {}
