"""Rapports: JSON, CSV, Markdown, et plan d'action structure."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from comparator import ComparePlan


def _ts() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _sanitize_csv(value):
    """Previent l'injection de formules CSV (CWE-1236)."""
    if isinstance(value, str):
        s = value.lstrip()
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
            return "'" + value
    return value


def write_json(plan: ComparePlan, out_dir: Path, name: str = "plan") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{_ts()}.json"
    path.write_text(json.dumps(plan.to_dict(), indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return path


def write_inventory_json(scan_dict: dict, out_dir: Path, name: str = "inventory") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}_{_ts()}.json"
    path.write_text(json.dumps(scan_dict, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    return path


def write_csv_duplicates(plan: ComparePlan, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"duplicates_{_ts()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["group_key", "size", "count", "hash", "cross_drive", "wasted_bytes",
                    "drives", "roots", "paths"])
        for g in plan.duplicate_groups:
            w.writerow([_sanitize_csv(v) for v in [
                g["key"], g["size"], g["count"], g.get("hash"), g.get("cross_drive"),
                g["wasted_bytes"],
                ";".join(g["drives"]), ";".join(g["roots"]),
                " | ".join(f["path"] for f in g["files"]),
            ]])
    return path


def write_csv_unique(plan: ComparePlan, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"unique_{_ts()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "root", "drive", "size", "reason"])
        for u in plan.unique_files:
            w.writerow([_sanitize_csv(v) for v in [u["path"], u["root"], u["drive"], u["size"], u["reason"]]])
    return path


def write_csv_inventory(files: List[Dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"inventory_{_ts()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "root", "drive", "size", "mtime", "ext", "partial_hash", "full_hash"])
        for f in files:
            w.writerow([_sanitize_csv(v) for v in [
                f.get("path"), f.get("root"), f.get("drive"), f.get("size"),
                f.get("mtime"), f.get("ext"), f.get("partial_hash"), f.get("full_hash"),
            ]])
    return path


def write_markdown(plan: ComparePlan, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report_{_ts()}.md"
    s = plan.summary
    lines = []
    lines.append("# Rapport de comparaison de systeme de fichiers")
    lines.append("")
    lines.append(f"- Racines: {', '.join(_md_escape(r) for r in plan.roots)}")
    lines.append(f"- Fichiers analyses: {s['total_files']}")
    lines.append(f"- Taille totale: {s['total_size_human']}")
    lines.append(f"- Groupes de taille: {s['num_size_groups']}")
    lines.append(f"- Groupes de doublons: {s['num_duplicate_groups']} "
                f"(dont cross-disque: {s['num_cross_drive_dup_groups']})")
    lines.append(f"- Fichiers uniques: {s['num_unique_files']}")
    lines.append(f"- Dossiers miroirs: {s['num_mirror_dirs']}")
    lines.append(f"- Espace recuperable: {s['recoverable_human']}")
    lines.append("")

    lines.append("## Statistiques par racine")
    lines.append("")
    lines.append("| Racine | Fichiers | Taille | Disques |")
    lines.append("|--------|----------|--------|---------|")
    for r in plan.per_root_stats:
        lines.append(f"| {_md_escape(r['root'])} | {r['files']} | {_human(r['size'])} | {','.join(r['drives'])} |")
    lines.append("")

    lines.append("## Top 20 plus gros fichiers")
    lines.append("")
    for f in plan.top_largest:
        lines.append(f"- `{_md_escape(f['path'])}` — {_human(f['size'])}")
    lines.append("")

    lines.append("## Repartition par extension")
    lines.append("")
    lines.append("| Extension | Fichiers | Taille |")
    lines.append("|-----------|----------|--------|")
    for e in plan.by_extension[:20]:
        lines.append(f"| {e['ext']} | {e['count']} | {_human(e['size'])} |")
    lines.append("")

    lines.append("## Dossiers vides")
    lines.append("")
    for d in plan.empty_dirs[:50]:
        lines.append(f"- `{_md_escape(d)}`")
    lines.append(f"\nTotal: {len(plan.empty_dirs)}")
    lines.append("")

    lines.append("## Liens symboliques casses")
    lines.append("")
    for l in plan.broken_symlinks[:50]:
        lines.append(f"- `{_md_escape(l)}`")
    lines.append(f"\nTotal: {len(plan.broken_symlinks)}")
    lines.append("")

    lines.append("## Dossiers dupliques")
    lines.append("")
    for df in plan.duplicate_folders[:20]:
        lines.append(f"- {df['dirs']} ({df['file_count']} fichiers, {_human(df['total_size'])})")
    lines.append("")

    lines.append("## Actions suggerees")
    lines.append("")
    for a in plan.suggested_actions:
        lines.append(f"- **[{a['priority'].upper()}]** {a['type']}: {a['description']}")
    lines.append("")

    lines.append("## Top doublons (par espace gaspille)")
    lines.append("")
    for g in plan.duplicate_groups[:20]:
        lines.append(f"### {g['key'][:16]}...  size={_human(g['size'])} count={g['count']} "
                    f"wasted={_human(g['wasted_bytes'])}")
        if g.get("most_complete"):
            mc = g["most_complete"]
            lines.append(f"  Meilleur: `{_md_escape(mc['path'])}` (date: {mc['mtime']}, taille: {_human(mc['size'])})")
        for f in g["files"]:
            marker = " [COMPLET]" if f.get("is_most_complete") else ""
            lines.append(f"  - `{_md_escape(f['path'])}`{marker}")
        lines.append("")

    lines.append("## Dossiers miroirs")
    lines.append("")
    for m in plan.mirror_dirs[:20]:
        lines.append(f"- `{_md_escape(m['relative_path'])}` -> {m['roots']} (fichiers communs: {m['common_files']})")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _human(n: int) -> str:
    for unit in ("B", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"


def _md_escape(s):
    """Echappe les caracteres speciaux Markdown dans un chemin."""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("|", "\\|")
