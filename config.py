"""Configuration de l'agent de scan/comparaison de systeme de fichiers.

Tous les chemins de sortie sont confines a E:\\ pour respecter la contrainte
"pas de fichiers dans C:".
"""
from __future__ import annotations

import os
import sys
# Ajouter le chemin des packages installes dans E: (disque C: plein)
sys.path.insert(0, "E:/python_packages")

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Racine obligatoire pour toutes les sorties (cache, rapports, logs).
OUTPUT_ROOT = Path("E:/agent_fs")
CACHE_DIR = OUTPUT_ROOT / "cache"
REPORTS_DIR = OUTPUT_ROOT / "reports"
LOGS_DIR = OUTPUT_ROOT / "logs"

# Temporaire: forcer TEMP/TMP vers E: pour eviter tout ecriture dans C:.
os.environ.setdefault("TEMP", "E:/temp/opencode")
os.environ.setdefault("TMP", "E:/temp/opencode")

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

# Taille minimale d'un fichier pour etre hashe (octets). Les fichiers vides sont
# traites comme un cas special (tous identiques).
MIN_HASH_SIZE = 1

# Taille des chunks pour le hashing (64 Ko).
CHUNK_SIZE = 64 * 1024

# Nombre de threads pour le hashing.
HASH_WORKERS = 8

# Taille du partial hash (premiers + derniers octets) pour filtrer rapidement.
PARTIAL_HASH_BYTES = 4096

# Extensions considerees comme "texte" (pour comparaison de contenu optionnelle).
TEXT_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".html", ".css", ".log", ".ini", ".cfg",
}

# Taille max pour lire un fichier texte en memoire (pour diff).
MAX_TEXT_DIFF_BYTES = 2 * 1024 * 1024  # 2 Mo


@dataclass
class ScanConfig:
    roots: List[str] = field(default_factory=list)
    excludes: Optional[List[str]] = None
    min_size: int = 0            # taille minimale (octets) pour inclure un fichier
    max_size: Optional[int] = None  # taille maximale (octets)
    extensions: Optional[List[str]] = None  # filtre d'extensions (None = tout)
    follow_symlinks: bool = False
    skip_symlinks: bool = False  # ignorer les liens symboliques
    incremental: bool = False     # scan incrementiel (cache de mtime par dossier)
    compute_hash: bool = True
    partial_hash_first: bool = True  # partial hash avant full hash
    hash_algorithm: str = "sha256"
    cache_db: Optional[str] = None   # chemin SQLite (None = default)
    workers: int = HASH_WORKERS
    io_threads: int = 2  # threads I/O par disque (2 pour HDD, 8+ pour SSD)
    io_throttle_ms: int = 0  # delai entre les lectures (0 = pas de throttle)
    output_dir: Optional[str] = None
    max_depth: Optional[int] = None  # profondeur max de scan (None = illimite)

    def __post_init__(self):
        if self.excludes is None:
            self.excludes = list(DEFAULT_EXCLUDES)

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
    min_duplicate_group: int = 2  # nb min de copies pour etre "doublon"


def ensure_dirs():
    for d in (OUTPUT_ROOT, CACHE_DIR, REPORTS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    Path(os.environ["TEMP"]).mkdir(parents=True, exist_ok=True)
