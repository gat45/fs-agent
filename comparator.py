"""Comparaison d'inventaires: par poids (taille) puis par contenu (hash).

Produit un "plan structure" decrivant:
- groupes de fichiers de meme taille
- groupes de doublons (meme contenu)
- fichiers uniques par disque/racine
- dossiers miroirs (meme structure relative)
- actions suggerees
"""
from __future__ import annotations

import os
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional

from config import CompareConfig


@dataclass
class SizeGroup:
    size: int
    count: int
    files: List[str]
    drives: List[str]


@dataclass
class DuplicateGroup:
    key: str
    size: int
    count: int
    hash: Optional[str]
    files: List[dict]
    drives: List[str]
    wasted_bytes: int


@dataclass
class UniqueFile:
    path: str
    root: str
    drive: str
    size: int
    reason: str


@dataclass
class MirrorDir:
    relative_path: str
    roots: List[str]
    file_count: int
    total_size: int


@dataclass
class ComparePlan:
    roots: List[str]
    total_files: int
    total_size: int
    size_groups: List[dict] = field(default_factory=list)
    duplicate_groups: List[dict] = field(default_factory=list)
    unique_files: List[dict] = field(default_factory=list)
    mirror_dirs: List[dict] = field(default_factory=list)
    top_largest: List[dict] = field(default_factory=list)
    by_extension: List[dict] = field(default_factory=list)
    same_name_groups: List[dict] = field(default_factory=list)
    empty_dirs: List[str] = field(default_factory=list)
    broken_symlinks: List[str] = field(default_factory=list)
    duplicate_folders: List[dict] = field(default_factory=list)
    scan_diff: dict = field(default_factory=dict)
    md_comparisons: List[dict] = field(default_factory=list)
    per_root_stats: List[dict] = field(default_factory=list)
    suggested_actions: List[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _group_by_size(files) -> Dict[int, List]:
    g = defaultdict(list)
    for f in files:
        g[f.size].append(f)
    return g


def _group_by_content(files) -> Dict[str, List]:
    g = defaultdict(list)
    for f in files:
        key = f.full_hash or f.partial_hash
        if key is None:
            key = f"__nohash__:{f.path}"
        g[key].append(f)
    return g


def _human(n: int) -> str:
    for unit in ("B", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"


def compare(files, cfg: CompareConfig, scan_result=None, history=None, previous_scan_id=None) -> ComparePlan:
    plan = ComparePlan(roots=sorted({f.root for f in files}),
                       total_files=len(files),
                       total_size=sum(f.size for f in files))

    # Empty dirs et broken symlinks depuis le scan
    if scan_result is not None:
        plan.empty_dirs = list(getattr(scan_result, "empty_dirs", []) or [])
        plan.broken_symlinks = list(getattr(scan_result, "broken_symlinks", []) or [])

    # Stats par racine
    per_root = defaultdict(lambda: {"root": "", "files": 0, "size": 0, "drives": set()})
    for f in files:
        r = per_root[f.root]
        r["root"] = f.root
        r["files"] += 1
        r["size"] += f.size
        r["drives"].add(f.drive)
    for r in per_root.values():
        r["drives"] = sorted(r["drives"])
        plan.per_root_stats.append(r)

    # Groupes par taille
    if cfg.by_size:
        size_groups_raw = _group_by_size(files)
        for size, grp in sorted(size_groups_raw.items(), key=lambda kv: (-kv[0],)):
            if len(grp) < 1:
                continue
            plan.size_groups.append({
                "size": size,
                "count": len(grp),
                "drives": sorted({f.drive for f in grp}),
                "roots": sorted({f.root for f in grp}),
                "files": [f.path for f in grp],
            })

    # Doublons de contenu
    cross_dups = []
    same_dups = []
    if cfg.by_content:
        content_groups = _group_by_content(files)
        for key, grp in content_groups.items():
            if len(grp) < cfg.min_duplicate_group:
                continue
            sizes = {f.size for f in grp}
            if len(sizes) != 1:
                continue
            size = grp[0].size
            drives = sorted({f.drive for f in grp})
            roots = sorted({f.root for f in grp})
            is_cross = len(drives) >= 2 or len(roots) >= 2
            inodes = {(f.drive, getattr(f, "inode", None)) for f in grp if getattr(f, "inode", None) is not None}
            is_hardlink_group = len(inodes) == 1 and len(grp) > 1 and all(
                getattr(f, "nlink", 1) > 1 for f in grp
            )
            most_complete = max(grp, key=lambda f: (f.mtime, f.size))
            dup = {
                "key": key,
                "size": size,
                "count": len(grp),
                "hash": grp[0].full_hash or grp[0].partial_hash,
                "drives": drives,
                "roots": roots,
                "cross_drive": is_cross,
                "wasted_bytes": 0 if is_hardlink_group else (len(grp) - 1) * size,
                "is_hardlink_group": is_hardlink_group,
                "most_complete": {
                    "path": most_complete.path,
                    "root": most_complete.root,
                    "drive": most_complete.drive,
                    "size": most_complete.size,
                    "mtime": most_complete.mtime,
                },
                "files": [{"path": f.path, "root": f.root, "drive": f.drive,
                           "mtime": f.mtime, "nlink": getattr(f, "nlink", 1),
                           "inode": getattr(f, "inode", None),
                           "is_most_complete": f.path == most_complete.path} for f in grp],
            }
            plan.duplicate_groups.append(dup)
            if is_cross:
                cross_dups.append(dup)
            else:
                same_dups.append(dup)
        plan.duplicate_groups.sort(key=lambda g: -g["wasted_bytes"])

    # Fichiers uniques
    if cfg.include_unique:
        content_groups = _group_by_content(files)
        for key, grp in content_groups.items():
            if len(grp) == 1:
                f = grp[0]
                plan.unique_files.append({
                    "path": f.path,
                    "root": f.root,
                    "drive": f.drive,
                    "size": f.size,
                    "reason": "unique_content",
                })

    # Dossiers miroirs
    roots_list = sorted({f.root for f in files})
    root_dir_files: Dict[str, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for f in files:
        rel = os.path.relpath(f.path, f.root)
        rdir = os.path.dirname(rel)
        if rdir == ".":
            rdir = ""
        root_dir_files[f.root][rdir].add(os.path.basename(f.path))

    mirror_candidates = []
    for i in range(len(roots_list)):
        for j in range(i + 1, len(roots_list)):
            r1, r2 = roots_list[i], roots_list[j]
            dirs1 = set(root_dir_files[r1].keys())
            dirs2 = set(root_dir_files[r2].keys())
            common = dirs1 & dirs2
            for d in common:
                s1 = root_dir_files[r1][d]
                s2 = root_dir_files[r2][d]
                inter = s1 & s2
                if len(inter) >= 1:
                    mirror_candidates.append((d, r1, r2, len(inter), len(s1), len(s2)))
    mirror_map: Dict[str, dict] = {}
    for d, r1, r2, inter, n1, n2 in mirror_candidates:
        key = d if d else "."
        if key not in mirror_map:
            mirror_map[key] = {
                "relative_path": key,
                "roots": set(),
                "common_files": 0,
                "file_counts": {},
            }
        mirror_map[key]["roots"].add(r1)
        mirror_map[key]["roots"].add(r2)
        mirror_map[key]["common_files"] = max(mirror_map[key]["common_files"], inter)
    for key, m in mirror_map.items():
        m["roots"] = sorted(m["roots"])
        ts = 0
        fc = 0
        for f in files:
            rel = os.path.relpath(f.path, f.root)
            if os.path.dirname(rel) == ("" if key == "." else key) or (key == "." and os.path.dirname(rel) == "."):
                if f.root == m["roots"][0]:
                    ts += f.size
                    fc += 1
        m["file_count"] = fc
        m["total_size"] = ts
        plan.mirror_dirs.append(m)
    plan.mirror_dirs.sort(key=lambda m: -m.get("common_files", 0))

    # Dossiers dupliques (contenu identique)
    folder_sigs = defaultdict(list)
    for d in set(os.path.dirname(f.path) for f in files):
        sig_files = []
        for f in files:
            if os.path.dirname(f.path) == d:
                sig_files.append((os.path.basename(f.path), f.size, f.full_hash or f.partial_hash))
        if not sig_files:
            continue
        sig = tuple(sorted(sig_files))
        folder_sigs[sig].append(d)
    for sig, dirs in folder_sigs.items():
        if len(dirs) >= 2:
            plan.duplicate_folders.append({
                "dirs": sorted(dirs),
                "file_count": len(sig),
                "total_size": sum(s for _, s, _ in sig),
            })
    plan.duplicate_folders.sort(key=lambda x: -x["total_size"])

    # Comparaison de rapports Markdown
    try:
        from md_compare import find_similar_md, compare_md_files
        md_files = [f.path for f in files if f.path.lower().endswith(".md")]
        if len(md_files) >= 2:
            similar_pairs = find_similar_md(md_files, threshold=0.3)
            for p1, p2, sim in similar_pairs[:20]:
                cmp = compare_md_files(p1, p2)
                plan.md_comparisons.append(cmp)
    except Exception:
        pass

    # Top plus gros fichiers
    top_largest = sorted(files, key=lambda f: -f.size)[:20]
    plan.top_largest = [
        {"path": f.path, "root": f.root, "drive": f.drive, "size": f.size} for f in top_largest
    ]

    # Stats par extension
    ext_stats = defaultdict(lambda: {"ext": "", "count": 0, "size": 0})
    for f in files:
        e = f.ext or "(sans extension)"
        es = ext_stats[e]
        es["ext"] = e
        es["count"] += 1
        es["size"] += f.size
    plan.by_extension = sorted(ext_stats.values(), key=lambda x: -x["size"])

    # Fichiers de meme nom (basename) sur disques differents
    if cfg.by_name:
        name_groups = defaultdict(list)
        for f in files:
            name_groups[os.path.basename(f.path)].append(f)
        for name, grp in name_groups.items():
            if len(grp) < 2:
                continue
            drives = sorted({f.drive for f in grp})
            roots = sorted({f.root for f in grp})
            plan.same_name_groups.append({
                "name": name,
                "count": len(grp),
                "drives": drives,
                "roots": roots,
                "cross_drive": len(drives) >= 2,
                "files": [{"path": f.path, "root": f.root, "drive": f.drive, "size": f.size}
                          for f in grp],
            })
        plan.same_name_groups.sort(key=lambda g: -g["count"])

    # Actions suggerees
    actions = []
    if cross_dups:
        total_wasted = sum(g["wasted_bytes"] for g in cross_dups)
        actions.append({
            "type": "review_cross_drive_duplicates",
            "priority": "high",
            "description": f"{len(cross_dups)} groupes de doublons cross-disque; "
                           f"{total_wasted} octets en double. A examiner (aucune suppression).",
            "count": len(cross_dups),
            "recoverable_bytes": total_wasted,
        })
    if same_dups:
        actions.append({
            "type": "review_same_drive_duplicates",
            "priority": "medium",
            "description": f"{len(same_dups)} groupes de doublons sur meme disque. A examiner.",
            "count": len(same_dups),
            "recoverable_bytes": sum(g["wasted_bytes"] for g in same_dups),
        })
    if plan.mirror_dirs:
        actions.append({
            "type": "sync_mirror_dirs",
            "priority": "medium",
            "description": f"{len(plan.mirror_dirs)} dossiers miroirs detectes; verifier la synchronisation.",
            "count": len(plan.mirror_dirs),
        })
    if plan.empty_dirs:
        actions.append({
            "type": "empty_dirs_found",
            "priority": "low",
            "description": f"{len(plan.empty_dirs)} dossiers vides detectes (aucune suppression).",
            "count": len(plan.empty_dirs),
        })
    if plan.broken_symlinks:
        actions.append({
            "type": "broken_symlinks_found",
            "priority": "medium",
            "description": f"{len(plan.broken_symlinks)} liens symboliques casses detectes.",
            "count": len(plan.broken_symlinks),
        })
    if plan.duplicate_folders:
        actions.append({
            "type": "review_duplicate_folders",
            "priority": "high",
            "description": f"{len(plan.duplicate_folders)} dossiers dupliques detectes. A examiner.",
            "count": len(plan.duplicate_folders),
            "recoverable_bytes": sum(d["total_size"] for d in plan.duplicate_folders),
        })
    if plan.unique_files:
        actions.append({
            "type": "backup_unique_files",
            "priority": "low",
            "description": f"{len(plan.unique_files)} fichiers uniques (sans doublon); candidats a la sauvegarde.",
            "count": len(plan.unique_files),
        })
    plan.suggested_actions = actions

    # Comparaison temporelle (memoire persistante)
    if history is not None and previous_scan_id is not None:
        try:
            diff = history.compare_scans(previous_scan_id, history.get_last_scan(scan_result.roots if scan_result else None)["scan_id"])
            plan.scan_diff = {
                "previous_scan_id": previous_scan_id,
                "current_scan_id": diff.get("new_total", 0),
                "files_added": len(diff.get("added", [])),
                "files_removed": len(diff.get("removed", [])),
                "files_modified": len(diff.get("modified", [])),
                "files_unchanged": diff.get("unchanged_count", 0),
                "added_paths": [f["path"] for f in diff.get("added", [])[:20]],
                "removed_paths": [f["path"] for f in diff.get("removed", [])[:20]],
                "modified_paths": [d["new"]["path"] for d in diff.get("modified", [])[:20]],
            }
        except Exception:
            pass

    # Resume
    plan.summary = {
        "total_files": plan.total_files,
        "total_size": plan.total_size,
        "total_size_human": _human(plan.total_size),
        "num_size_groups": len(plan.size_groups),
        "num_duplicate_groups": len(plan.duplicate_groups),
        "num_cross_drive_dup_groups": len(cross_dups),
        "num_unique_files": len(plan.unique_files),
        "num_mirror_dirs": len(plan.mirror_dirs),
        "num_top_largest": len(plan.top_largest),
        "num_same_name_groups": len(plan.same_name_groups),
        "num_empty_dirs": len(plan.empty_dirs),
        "num_broken_symlinks": len(plan.broken_symlinks),
        "num_duplicate_folders": len(plan.duplicate_folders),
        "num_md_comparisons": len(plan.md_comparisons),
        "recoverable_bytes": sum(g["wasted_bytes"] for g in plan.duplicate_groups),
        "recoverable_human": _human(sum(g["wasted_bytes"] for g in plan.duplicate_groups)),
        "roots": plan.roots,
    }
    return plan