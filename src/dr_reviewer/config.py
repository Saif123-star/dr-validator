from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = REPOSITORY_ROOT / "config" / "review"


def load_review_config(name: str) -> dict[str, Any]:
    path = CONFIG_ROOT / name
    try:
        with path.open(encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"Unable to load review configuration {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"Review configuration {path} must contain a YAML mapping")
    return config


PIPELINE_CONFIG = load_review_config("pipeline_dr_review.yaml")
SEVERITY_CONFIG = load_review_config("severity_rules.yaml")
SOURCE_AUTHORITY_CONFIG = load_review_config("source_authority.yaml")
CONFLUENCE_CONFIG = load_review_config("confluence.yaml")

if not isinstance(PIPELINE_CONFIG.get("tracks"), dict):
    raise ValueError("pipeline_dr_review.yaml must define a tracks mapping")
if not isinstance(SEVERITY_CONFIG.get("levels"), dict):
    raise ValueError("severity_rules.yaml must define a levels mapping")
if not isinstance(SOURCE_AUTHORITY_CONFIG.get("source_types"), dict):
    raise ValueError("source_authority.yaml must define a source_types mapping")
if not isinstance(PIPELINE_CONFIG.get("stages"), dict):
    raise ValueError("pipeline_dr_review.yaml must define a stages mapping")
for _key in ("request_timeout_seconds", "max_response_bytes", "max_attachment_bytes"):
    if not isinstance(CONFLUENCE_CONFIG.get(_key), int) or CONFLUENCE_CONFIG[_key] <= 0:
        raise ValueError(f"confluence.yaml must define a positive integer {_key}")


def load_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from a dotenv file without touching os.environ."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key.isidentifier():
            raise ValueError(f"{path.name} line {number} must use KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values
