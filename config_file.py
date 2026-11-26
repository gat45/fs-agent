"""Configuration par fichier JSON pour l'agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

CONFIG_PATH = Path("E:/agent_fs/config.json")

DEFAULT_CONFIG = {
    "roots": [],
    "all_drives": True,
    "excludes": None,
    "min_size": 0,
    "max_size": None,
    "extensions": None,
    "max_depth": None,
    "follow_symlinks": False,
    "skip_symlinks": False,
    "incremental": False,
    "compute_hash": True,
    "partial_only": False,
    "workers": 8,
    "io_threads": 2,
    "io_throttle_ms": 0,
    "sequential": False,
    "min_dup": 2,
    "no_unique": False,
    "no_by_name": False,
    "no_by_size": False,
    "dest": "E:\\",
    "output": None,
    "dashboard": False,
}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """Charge la configuration depuis un fichier JSON."""
    if path is None:
        path = CONFIG_PATH
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Fusionner avec les defaults
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg)
        # Valider les types
        for key, default_val in DEFAULT_CONFIG.items():
            if key in merged and merged[key] is not None:
                if type(merged[key]) is not type(default_val) and default_val is not None:
                    merged[key] = default_val
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_CONFIG)


def save_config(cfg: Dict[str, Any], path: Optional[Path] = None):
    """Sauvegarde la configuration dans un fichier JSON."""
    if path is None:
        path = CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def create_default_config():
    """Cree un fichier de configuration par defaut."""
    save_config(DEFAULT_CONFIG)
    print(f"Configuration par defaut creee: {CONFIG_PATH}")