"""Layered config merge with locked invariants.

Layers: framework defaults -> workspace.yaml -> repo-policy.yaml.
Maps merge deeply, scalars and lists are replaced by the later layer.
Paths under `locked:` in the defaults cannot be changed by any layer.
"""
import copy
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "framework" / "schemas"
LAYERS = ("defaults", "workspace", "repo-policy")


class ConfigError(Exception):
    pass


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return data


def validate(layer, data, source):
    schema = json.loads((SCHEMA_DIR / f"{layer}.schema.json").read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [f"{source}: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
        raise ConfigError("\n".join(lines))


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def expand_dotted(flat):
    """{'a.b': 1} -> {'a': {'b': 1}}"""
    out = {}
    for dotted, value in flat.items():
        node = out
        *parents, leaf = dotted.split(".")
        for p in parents:
            node = node.setdefault(p, {})
            if not isinstance(node, dict):
                raise ConfigError(f"override '{dotted}' conflicts with another override")
        node[leaf] = value
    return out


def get_path(cfg, dotted):
    node = cfg
    for p in dotted.split("."):
        if not isinstance(node, dict) or p not in node:
            return None
        node = node[p]
    return node


def merge_layers(defaults, workspace=None, repo=None):
    """Validate and merge. Raises ConfigError on schema or locked-invariant violations."""
    validate("defaults", defaults, "defaults")
    locked = defaults["locked"]
    merged = deep_merge({k: v for k, v in defaults.items() if k != "locked"}, expand_dotted(locked))
    for name, layer in (("workspace", workspace), ("repo-policy", repo)):
        if layer is None:
            continue
        validate(name, layer, name)
        patch = {k: v for k, v in layer.items() if k != "overrides"}
        patch = deep_merge(patch, expand_dotted(layer.get("overrides", {})))
        merged = deep_merge(merged, patch)
        for path, required in locked.items():
            if get_path(merged, path) != required:
                raise ConfigError(f"{name}: locked key '{path}' cannot be overridden")
    merged["locked"] = locked
    return merged


def load_config(defaults_path, workspace_path=None, repo_policy_path=None):
    return merge_layers(
        load_yaml(defaults_path),
        load_yaml(workspace_path) if workspace_path else None,
        load_yaml(repo_policy_path) if repo_policy_path else None,
    )
