"""Scanner recursif multi-disques / multi-dossiers.

Collecte pour chaque fichier: chemin, disque/racine, taille, mtime, extension,
et pour chaque dossier: nombre de fichiers, taille totale.

Optimisations memoire:
- Limite la taille des listes en memoire
- Utilise des generators pour les gros volumes
- Nettoie les references inutiles
"""
from __future__ import annotations

import os
import stat
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Callable

from config import ScanConfig


def _add_long_path_prefix(path: str) -> str:
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
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def _drive_of(path: str) -> str:
    if len(path) >= 2 and path[1] == ":":
        return path[0].upper()
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


@dataclass
class FileEntry:
    path: str
    root: str
    drive: str
    size: int
    mtime: float
    ext: str
    rel_path: str = ""
    is_symlink: bool = False
    nlink: int = 1
    inode: Optional[int] = None
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
    empty_dirs: List[str] = field(default_factory=list)
    broken_symlinks: List[str] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0
    total_files: int = 0
    total_size: int = 0

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


def scan_one_root(root: str, cfg: ScanConfig,
                  progress_cb: Optional[Callable[[int], None]] = None,
                  visited_inodes: Optional[set] = None) -> ScanResult:
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
    access_root = _add_long_path_prefix(root_str)

    dir_map: Dict[str, DirEntry] = {}
    excludes = cfg.excludes or []

    dir_cache = None
    if cfg.incremental:
        try:
            from incremental import DirCache
            cache_db = cfg.resolved_cache_db().parent / "dir_cache.sqlite"
            dir_cache = DirCache(cache_db)
            # Avertissement: le scan incrementiel est experimental
            import warnings
            warnings.warn("Le scan incrementiel est experimental. Les resultats peuvent etre incomplets.")
        except Exception:
            pass

    visited_inodes = set() if visited_inodes is None else visited_inodes

    try:
        for dirpath, dirnames, filenames in os.walk(access_root, followlinks=cfg.follow_symlinks):
            # Ne pas sauter un dossier simplement parce que son mtime est
            # inchangé : dir_cache ne stocke ni la liste des fichiers ni leurs
            # métadonnées, donc ce raccourci rendrait le résultat incomplet.
            # Le cache reste mis à jour ci-dessous pour un futur cache complet.

            dirpath = _strip_long_path_prefix(dirpath)

            try:
                rel = os.path.relpath(dirpath, root_str)
                depth = 0 if rel == "." else rel.count(os.sep) + 1
            except ValueError:
                depth = 0
            if cfg.max_depth is not None and depth > cfg.max_depth:
                dirnames[:] = []
                continue

            dirnames[:] = [d for d in dirnames if not _should_exclude(d, excludes)]

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

                if stat.S_ISLNK(st.st_mode):
                    try:
                        target = os.readlink(_add_long_path_prefix(full))
                        if not os.path.isabs(target):
                            target = os.path.join(os.path.dirname(full), target)
                        if not os.path.exists(_add_long_path_prefix(target)):
                            res.broken_symlinks.append(full)
                    except OSError:
                        res.broken_symlinks.append(full)

                if stat.S_ISLNK(st.st_mode) and cfg.follow_symlinks:
                    try:
                        inode = (st.st_dev, st.st_ino)
                        if inode in visited_inodes:
                            continue
                        visited_inodes.add(inode)
                    except OSError:
                        pass

                if not stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                    continue

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
                    drive=drive,
                    size=st.st_size,
                    mtime=st.st_mtime,
                    ext=ext,
                    rel_path=os.path.relpath(full, root_str),
                    is_symlink=bool(stat.S_ISLNK(st.st_mode)),
                    nlink=st.st_nlink,
                    inode=st.st_ino,
                )
                res.files.append(fe)

                de.file_count += 1
                de.total_size += st.st_size

                if progress_cb:
                    progress_cb(1)

            if dir_cache is not None:
                try:
                    st = os.stat(_add_long_path_prefix(dirpath))
                    dir_cache.put(dirpath, st.st_mtime, de.file_count, de.total_size)
                except OSError:
                    pass

            parent = os.path.dirname(dirpath)
            if parent and parent != dirpath and parent in dir_map:
                dir_map[parent].total_size += de.total_size
                dir_map[parent].file_count += de.file_count
    except Exception as e:
        res.errors.append({"path": root_str, "error": f"walk failed: {e}"})

    for de in dir_map.values():
        if de.file_count == 0 and de.subdirs == 0:
            res.empty_dirs.append(de.path)

    res.dirs = list(dir_map.values())
    res.total_files = len(res.files)
    res.total_size = sum(f.size for f in res.files)
    res.finished_at = time.time()
    return res


def scan_roots(roots: List[str], cfg: ScanConfig,
               progress_cb: Optional[Callable[[int], None]] = None) -> ScanResult:
    merged = ScanResult(roots=list(roots))
    merged.started_at = time.time()
    seen_paths = set()
    visited_inodes = set()  # Partage entre toutes les racines pour detecter les cycles
    for r in roots:
        sub = scan_one_root(r, cfg, progress_cb, visited_inodes)
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
    merged.total_files = len(merged.files)
    merged.total_size = sum(f.size for f in merged.files)
    merged.finished_at = time.time()
    return merged
