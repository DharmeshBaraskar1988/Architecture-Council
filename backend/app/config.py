"""Loads YAML config from the repository's config/ folder."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("COUNCIL_CONFIG_DIR", REPO_ROOT / "config"))
DATA_DIR = Path(os.environ.get("COUNCIL_DATA_DIR", REPO_ROOT / "data"))


def load_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=None)
def config(name: str) -> Any:
    """config('consensus') -> contents of config/consensus.yaml"""
    return load_yaml(CONFIG_DIR / f"{name}.yaml")


def load_dir(sub: str) -> list[dict]:
    """All YAML files in a config sub-folder, e.g. load_dir('frameworks')."""
    folder = CONFIG_DIR / sub
    return [load_yaml(p) for p in sorted(folder.glob("*.yaml"))]


def data_dir() -> Path:
    """The data folder, read at call time so tests can point it at a temporary folder."""
    return Path(os.environ.get("COUNCIL_DATA_DIR", REPO_ROOT / "data"))


def mock_mode() -> bool:
    return os.environ.get("COUNCIL_MOCK_LLM", "0") == "1"
