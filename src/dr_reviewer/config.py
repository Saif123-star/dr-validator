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

if not isinstance(PIPELINE_CONFIG.get("tracks"), dict):
    raise ValueError("pipeline_dr_review.yaml must define a tracks mapping")
if not isinstance(SEVERITY_CONFIG.get("levels"), dict):
    raise ValueError("severity_rules.yaml must define a levels mapping")
if not isinstance(SOURCE_AUTHORITY_CONFIG.get("source_types"), dict):
    raise ValueError("source_authority.yaml must define a source_types mapping")
