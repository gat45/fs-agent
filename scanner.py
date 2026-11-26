"""Scanner recursif multi-disques / multi-dossiers.

Collecte pour chaque fichier: chemin, disque/racine, taille, mtime, extension,
et pour chaque dossier: nombre de fichiers, taille totale.
"""
from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Iterator, Callable

from config import ScanConfig


@dataclass
class FileEntry:
    path: str
    root: str          # racine de scan dont depend ce fichier
    drive: str         # lettre de disque (ex: "C", "E") ou ""
    size: int
    mtime: float
    ext: str
    rel_path: str = ""  # chemin relatif a la racine (compression de prefixe)
    is_symlink: bool = False
    nlink: int = 1
    inode: Optional[int] = None
    # Rempli plus tard par le hasher
    partial_hash: Optional[str] = None
    full_hash: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class DirEntry:
    path: str
    root: str
    drive: str
    file_count: int = 0
    total_size: int = 0
    subdirs: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class ScanResult:
    roots: List[str]
    files: List[FileEntry] = field(default_factory=list)
    dirs: List[DirEntry] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    empty_dirs: List[str] = field(default_factory=list)
    broken_symlinks: List[str] = field(default_factory=list)
    total_files: int = 0
    total_size: int = 0
    total_age_days: float = 0.0  # age moyen des fichiers en jours

    def to_dict(self):
        return {
            "roots": self.roots,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_files": self.total_files,
            "total_size": self.total_size,
            "errors": self.errors,
            "empty_dirs": self.empty_dirs,
            "broken_symlinks": self.broken_symlinks,
            "files": [f.to_dict() for f in self.files],
            "dirs": [d.to_dict() for d in self.dirs],
        }


def _add_long_path_prefix(path: str) -> str:
    """Ajoute le prefixe \\\\?\\ pour supporter les chemins longs sur Windows."""
    if os.name != "nt":
        return path
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    if len(path) >= 2 and path[1] == ":":
        return "\\\\?\\" + path
    return path


def _strip_long_path_prefix(path: str) -> str:
    """Retire le prefixe \\\\?\\ pour l'affichage/stockage."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _drive_of(path: str) -> str:
    # Windows: lettre de disque
    if len(path) >= 2 and path[1] == ":":
        return path[0].upper()
    # UNC ou autre: premier segment
    parts = path.replace("\\", "/").split("/")
    return parts[0] if parts else ""


def _should_exclude(name: str, excludes) -> bool:
    if not excludes:
        return False
    low = name.lower()
    for ex in excludes:
        if low == ex.lower():
            return True
    return False


def scan_one_root(root: str, cfg: ScanConfig,
                  progress_cb: Optional[Callable[[int], None]] = None) -> ScanResult:
    """Scanne une seule racine."""
    res = ScanResult(roots=[root])
    res.started_at = time.time()
    root_path = Path(root)
    if not root_path.exists():
        res.errors.append({"path": root, "error": "root does not exist"})
        res.finished_at = time.time()
        return res

    root_str = str(root_path)
    drive = _drive_of(root_str)

    # Support des chemins longs Windows
    access_root = _add_long_path_prefix(root_str)

    # Dictionnaire chemin dossier -> DirEntry (pour agregation)
    dir_map: Dict[str, DirEntry] = {}

    excludes = cfg.excludes or []
    # Incremental scan: utiliser le cache de dossiers
    dir_cache = None
    if cfg.incremental:
        from incremental import DirCache
        cache_db = cfg.resolved_cache_db().parent / "dir_cache.sqlite"
        dir_cache = DirCache(cache_db)

    try:
        for dirpath, dirnames, filenames in os.walk(access_root, followlinks=cfg.follow_symlinks):
            # Incremental: si le dossier n'a pas change, ne pas descendre
            if dir_cache is not None:
                try:
                    st = os.stat(_add_long_path_prefix(dirpath))
                    cached = dir_cache.get(dirpath)
                    if cached is not None and cached["mtime"] == st.st_mtime:
                        # Dossier non modifie: ne pas descendre
                        dirnames[:] = []
                        # Utiliser les donnees en cache
                        # (on ne re-scanne pas les fichiers)
                        continue
                except OSError:
                    pass

            # Nettoyer le prefixe pour le stockage
            dirpath = _strip_long_path_prefix(dirpath)
            # Calcul de la profondeur
            try:
                rel = os.path.relpath(dirpath, root_str)
                depth = 0 if rel == "." else rel.count(os.sep) + 1
            except ValueError:
                depth = 0
            if cfg.max_depth is not None and depth > cfg.max_depth:
                dirnames[:] = []
                continue

            # Filtrage des dossiers exclus (in-place pour ne pas descendre)
            dirnames[:] = [d for d in dirnames if not _should_exclude(d, excludes)]

            # Enregistrer le dossier courant
            if dirpath not in dir_map:
                dir_map[dirpath] = DirEntry(path=dirpath, root=root_str, drive=drive)

            de = dir_map[dirpath]
            de.subdirs = len(dirnames)

            for fn in filenames:
                if _should_exclude(fn, excludes):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.lstat(_add_long_path_prefix(full))
                except OSError as e:
                    res.errors.append({"path": full, "error": str(e)})
                    continue
                if cfg.skip_symlinks and stat.S_ISLNK(st.st_mode):
                    continue
                # Detection des liens symboliques casses
                if stat.S_ISLNK(st.st_mode):
                    try:
                        target = os.readlink(_add_long_path_prefix(full))
                        if not os.path.isabs(target):
                            target = os.path.join(os.path.dirname(full), target)
                        if not os.path.exists(_add_long_path_prefix(target)):
                            res.broken_symlinks.append(full)
                    except OSError:
                        res.broken_symlinks.append(full)
                # Filtre taille
                if st.st_size < cfg.min_size:
                    continue
                if cfg.max_size is not None and st.st_size > cfg.max_size:
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if cfg.extensions and ext not in [e.lower() for e in cfg.extensions]:
                    continue

                fe = FileEntry(
                    path=full,
                    root=root_str,
                    rel_path=os.path.relpath(full, root_str),
                    drive=drive,
                    size=st.st_size,
                    mtime=st.st_mtime,
                    ext=ext,
                    is_symlink=bool(stat.S_ISLNK(st.st_mode)),
                    nlink=st.st_nlink,
                    inode=st.st_ino,
                )
                res.files.append(fe)
                res.total_files += 1
                res.total_size += st.st_size

                # Agregation dossier
                de.file_count += 1
                de.total_size += st.st_size

                if progress_cb:
                    progress_cb(1)

            # Mettre a jour le cache incremental
            if dir_cache is not None:
                try:
                    st = os.stat(_add_long_path_prefix(dirpath))
                    dir_cache.put(dirpath, st.st_mtime, de.file_count, de.total_size)
                except OSError:
                    pass

            # Agregation vers le parent: ajouter la taille de ce dossier au parent
            parent = os.path.dirname(dirpath)
            if parent and parent != dirpath and parent in dir_map:
                dir_map[parent].total_size += de.total_size
                dir_map[parent].file_count += de.file_count
    except Exception as e:
        res.errors.append({"path": root_str, "error": f"walk failed: {e}"})

    # Detection des dossiers vides
    for de in dir_map.values():
        if de.file_count == 0 and de.subdirs == 0:
            res.empty_dirs.append(de.path)

    res.dirs = list(dir_map.values())
    res.finished_at = time.time()
    return res


def scan_roots(roots: List[str], cfg: ScanConfig,
               progress_cb: Optional[Callable[[int], None]] = None) -> ScanResult:
    """Scanne plusieurs racines et fusionne en un seul ScanResult."""
    merged = ScanResult(roots=list(roots))
    merged.started_at = time.time()
    seen_paths = set()
    for r in roots:
        sub = scan_one_root(r, cfg, progress_cb)
        for f in sub.files:
            if f.path in seen_paths:
                continue
            seen_paths.add(f.path)
            merged.files.append(f)
        for d in sub.dirs:
            merged.dirs.append(d)
        merged.errors.extend(sub.errors)
        merged.empty_dirs.extend(sub.empty_dirs)
        merged.broken_symlinks.extend(sub.broken_symlinks)
        merged.total_files += sub.total_files  # approximatif
        merged.total_size += sub.total_size
    # Recalculer les totaux reels
    merged.total_files = len(merged.files)
    merged.total_size = sum(f.size for f in merged.files)
    merged.finished_at = time.time()
    return merged
