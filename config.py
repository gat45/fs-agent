"""Configuration de l'agent de scan/comparaison de systeme de fichiers.

Tous les chemins de sortie sont confines a un disque configurable pour
respecter la contrainte "pas de fichiers dans C:".
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Ajouter le chemin des packages installes dans E: (disque C: plein)
sys.path.insert(0, "E:/python_packages")

# Racine des sorties : chemin explicite via FS_AGENT_HOME, E: sous Windows,
# emplacement cache portable sous Linux/macOS.
if os.environ.get("FS_AGENT_HOME"):
    OUTPUT_ROOT = Path(os.environ["FS_AGENT_HOME"]).expanduser()
elif os.name == "nt":
    OUTPUT_ROOT = Path("E:/agent_fs")
else:
    OUTPUT_ROOT = Path.home() / ".cache" / "fs-agent"

CACHE_DIR = OUTPUT_ROOT / "cache"
REPORTS_DIR = OUTPUT_ROOT / "reports"
LOGS_DIR = OUTPUT_ROOT / "logs"

# Respecter l'environnement existant et eviter de supposer l'existence du disque E:.
TEMP_ROOT = Path(os.environ.get("FS_AGENT_TEMP", (
    "E:/temp/opencode" if os.name == "nt"
    else str(Path.home() / ".cache" / "fs-agent" / "tmp")
))).expanduser()
os.environ.setdefault("TEMP", str(TEMP_ROOT))
os.environ.setdefault("TMP", str(TEMP_ROOT))

# Dossiers systeme a ignorer par defaut (Windows).
DEFAULT_EXCLUDES = [
    "System Volume Information",
    "$Recycle.Bin",
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "Recovery",
    "PerfLogs",
    "hiberfil.sys",
    "pagefile.sys",
    "swapfile.sys",
]

MIN_HASH_SIZE = 1
CHUNK_SIZE = 64 * 1024
HASH_WORKERS = 8
PARTIAL_HASH_BYTES = 4096

TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".html", ".css", ".log", ".ini", ".cfg",
}

MAX_TEXT_DIFF_BYTES = 2 * 1024 * 1024


@dataclass
class ScanConfig:
    roots: List[str] = field(default_factory=list)
    excludes: Optional[List[str]] = None
    min_size: int = 0
    max_size: Optional[int] = None
    extensions: Optional[List[str]] = None
    max_depth: Optional[int] = None
    follow_symlinks: bool = False
    skip_symlinks: bool = False
    incremental: bool = False
    compute_hash: bool = True
    partial_hash_first: bool = True
    hash_algorithm: str = "sha256"
    cache_db: Optional[str] = None
    workers: int = HASH_WORKERS
    io_threads: int = 2
    io_throttle_ms: int = 0
    sequential: bool = False
    output_dir: Optional[str] = None

    def __post_init__(self):
        if self.excludes is None:
            self.excludes = list(DEFAULT_EXCLUDES)
        # Validation des parametres
        self.workers = max(1, int(self.workers))
        self.io_threads = max(1, int(self.io_threads))
        if self.min_size < 0:
            self.min_size = 0
        if self.max_size is not None and self.max_size < 0:
            self.max_size = None
        if self.max_size is not None and self.max_size < self.min_size:
            raise ValueError("max_size doit etre superieur ou egal a min_size")
        if self.io_throttle_ms < 0:
            self.io_throttle_ms = 0
        if self.max_depth is not None and self.max_depth < 1:
            self.max_depth = None
        if self.extensions:
            self.extensions = [e.lower() for e in self.extensions]

    def resolved_cache_db(self) -> Path:
        if self.cache_db:
            return Path(self.cache_db)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / "hash_cache.sqlite"

    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            p = Path(self.output_dir)
        else:
            p = REPORTS_DIR
        p.mkdir(parents=True, exist_ok=True)
        return p


@dataclass
class CompareConfig:
    by_size: bool = True
    by_content: bool = True
    by_name: bool = True
    cross_drive: bool = True
    include_unique: bool = True
    include_duplicates: bool = True
    min_duplicate_group: int = 2

    def __post_init__(self):
        if self.min_duplicate_group < 2:
            self.min_duplicate_group = 2


def ensure_dirs():
    for d in (OUTPUT_ROOT, CACHE_DIR, REPORTS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    Path(os.environ["TEMP"]).mkdir(parents=True, exist_ok=True)