"""Module de consolidation de doublons: analyse, plan, aucune suppression.

Pour chaque groupe de doublons, determine:
- Le fichier le plus "complet" (le plus recent, le plus gros, le plus d'infos)
- Les differences de contenu entre les copies
- Un plan de consolidation (copier les fichiers manquants, merger les diffs)
- Aucune action n'est executee sans confirmation explicite de l'utilisateur.
"""
from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class FileCompleteness:
    """Score de completude d'un fichier."""
    path: str
    size: int
    mtime: float
    mtime_human: str
    has_more_content: bool = False  # True si ce fichier a plus de contenu qu'un autre
    content_lines: int = 0
    content_bytes: int = 0
    is_most_complete: bool = False
    completeness_score: float = 0.0
    reasons: List[str] = field(default_factory=list)


@dataclass
class ConsolidationAction:
    """Une action de consolidation proposee (jamais executee sans confirmation)."""
    action_type: str  # "keep", "copy", "merge", "archive", "review"
    source: str
    destination: Optional[str] = None
    reason: str = ""
    requires_confirmation: bool = True
    ai_analysis: Optional[str] = None


@dataclass
class ConsolidationPlan:
    """Plan de consolidation pour un groupe de doublons."""
    group_key: str
    size: int
    file_count: int
    most_complete_path: str = ""
    completeness_scores: List[Dict] = field(default_factory=list)
    actions: List[Dict] = field(default_factory=list)
    diff_summary: str = ""
    ai_recommendation: str = ""
    no_data_loss: bool = True  # Garantie: aucune suppression


def compute_completeness(f) -> FileCompleteness:
    """Calcule le score de completude d'un fichier."""
    import time
    fc = FileCompleteness(
        path=f.path,
        size=f.size,
        mtime=f.mtime,
        mtime_human=__import__("datetime").datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M:%S") if f.mtime > 0 else "N/A",
    )
    # Score de base: taille + recence
    fc.completeness_score = f.size * 0.3 + (f.mtime * 0.001 if f.mtime > 0 else 0)
    fc.reasons.append(f"taille={f.size} octets")
    fc.reasons.append(f"date={fc.mtime_human}")

    # Pour les fichiers texte, compter les lignes
    ext = getattr(f, "ext", "") or os.path.splitext(f.path)[1].lower()
    text_exts = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".xml",
                 ".yaml", ".yml", ".html", ".css", ".log", ".ini", ".cfg", ".java",
                 ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sh", ".bat"}
    if ext in text_exts and f.size < 10 * 1024 * 1024:  # < 10 Mo
        try:
            with open(f.path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
                fc.content_lines = content.count("\n") + 1
                fc.content_bytes = len(content.encode("utf-8"))
                fc.completeness_score += fc.content_lines * 0.5
                fc.reasons.append(f"lignes={fc.content_lines}")
        except (OSError, IOError, UnicodeDecodeError):
            pass

    return fc


def analyze_text_diff(path1: str, path2: str) -> str:
    """Analyse les differences entre deux fichiers texte."""
    try:
        with open(path1, "r", encoding="utf-8", errors="replace") as f1:
            content1 = f1.read()
        with open(path2, "r", encoding="utf-8", errors="replace") as f2:
            content2 = f2.read()
    except (OSError, IOError, UnicodeDecodeError):
        return "Impossible de lire les fichiers (binaire ou erreur)."

    if content1 == content2:
        return "Contenus identiques."

    lines1 = content1.splitlines()
    lines2 = content2.splitlines()

    # Differences simples
    only_in_1 = set(lines1) - set(lines2)
    only_in_2 = set(lines2) - set(lines1)

    diff_parts = []
    if only_in_1:
        diff_parts.append(f"Lignes uniquement dans {os.path.basename(path1)}: {len(only_in_1)}")
    if only_in_2:
        diff_parts.append(f"Lignes uniquement dans {os.path.basename(path2)}: {len(only_in_2)}")

    # Taille
    diff_parts.append(f"Taille: {len(content1)} vs {len(content2)} octets")

    return "; ".join(diff_parts) if diff_parts else "Differences mineures."


def create_consolidation_plan(group: dict, dest_dir: Optional[str] = None) -> ConsolidationPlan:
    """Cree un plan de consolidation pour un groupe de doublons.

    Aucune action n'est executee. Le plan est propose a l'utilisateur.
    """
    files = group["files"]
    cp = ConsolidationPlan(
        group_key=group["key"],
        size=group["size"],
        file_count=group["count"],
    )

    # Calculer la completude de chaque fichier
    completeness_list = []
    for f in files:
        # Reconstruire un objet FileEntry-like
        class FE:
            pass
        fe = FE()
        fe.path = f["path"]
        fe.size = f.get("size", group["size"])
        fe.mtime = f.get("mtime", 0)
        fe.ext = os.path.splitext(f["path"])[1].lower()
        fc = compute_completeness(fe)
        completeness_list.append(fc)

    # Trier par score de completude (decroissant)
    completeness_list.sort(key=lambda x: -x.completeness_score)

    # Le plus complet est le premier
    if completeness_list:
        cp.most_complete_path = completeness_list[0].path
        completeness_list[0].is_most_complete = True

    cp.completeness_scores = [
        {
            "path": fc.path,
            "size": fc.size,
            "mtime": fc.mtime_human,
            "score": round(fc.completeness_score, 2),
            "lines": fc.content_lines,
            "is_most_complete": fc.is_most_complete,
            "reasons": fc.reasons,
        }
        for fc in completeness_list
    ]

    # Analyser les differences entre le plus complet et les autres
    if len(files) >= 2:
        mc_path = completeness_list[0].path
        diffs = []
        for fc in completeness_list[1:]:
            diff = analyze_text_diff(mc_path, fc.path)
            diffs.append(f"{os.path.basename(fc.path)}: {diff}")
        cp.diff_summary = " | ".join(diffs) if diffs else "Aucune difference."

    # Creer les actions proposees (aucune execution)
    mc = completeness_list[0] if completeness_list else None
    if mc:
        # Action 1: garder le fichier le plus complet comme reference
        cp.actions.append({
            "action_type": "keep",
            "source": mc.path,
            "destination": mc.path,
            "reason": f"Fichier le plus complet (score={round(mc.completeness_score, 2)})",
            "requires_confirmation": False,
        })

        # Action 2: pour chaque doublon, proposer de le copier vers la destination
        # (si une destination est specifiee) ou de l'archiver
        for fc in completeness_list[1:]:
            if dest_dir:
                dest_path = os.path.join(dest_dir, os.path.basename(fc.path))
                cp.actions.append({
                    "action_type": "copy",
                    "source": fc.path,
                    "destination": dest_path,
                    "reason": f"Copier vers {dest_dir} (consolidation)",
                    "requires_confirmation": True,
                })
            else:
                cp.actions.append({
                    "action_type": "archive",
                    "source": fc.path,
                    "destination": None,
                    "reason": "Archiver (conserver sans suppression)",
                    "requires_confirmation": True,
                })

        # Action 3: merger les differences si les fichiers texte diffèrent
        if cp.diff_summary and "identiques" not in cp.diff_summary.lower():
            cp.actions.append({
                "action_type": "merge",
                "source": mc.path,
                "destination": mc.path,
                "reason": f"Fusionner les differences: {cp.diff_summary}",
                "requires_confirmation": True,
                "ai_analysis": None,  # A remplir par l'IA si necessaire
            })

    cp.ai_recommendation = (
        f"Le fichier le plus complet est {cp.most_complete_path}. "
        f"Les {len(files)-1} autres copies peuvent etre archivees (pas supprimees). "
        f"Utilisez l'IA pour analyser les differences de contenu si necessaire."
    )

    return cp


def create_full_consolidation_plan(duplicate_groups: List[dict],
                                  dest_dir: Optional[str] = None) -> List[ConsolidationPlan]:
    """Cree un plan de consolidation pour tous les groupes de doublons."""
    plans = []
    for g in duplicate_groups:
        if g.get("is_hardlink_group"):
            continue  # Les hardlinks sont le meme fichier
        cp = create_consolidation_plan(g, dest_dir)
        plans.append(cp)
    return plans


def format_consolidation_plan(plans: List[ConsolidationPlan]) -> str:
    """Formate le plan de consolidation en texte lisible."""
    lines = []
    lines.append("=" * 60)
    lines.append("PLAN DE CONSOLIDATION (AUCUNE SUPPRESSION AUTOMATIQUE)")
    lines.append("=" * 60)
    lines.append("")

    for i, cp in enumerate(plans, 1):
        lines.append(f"--- Groupe {i}: {cp.group_key[:16]}... ---")
        lines.append(f"  Taille: {cp.size} octets | Copies: {cp.file_count}")
        lines.append(f"  Fichier le plus complet: {cp.most_complete_path}")
        lines.append("")
        lines.append("  Scores de completude:")
        for cs in cp.completeness_scores:
            marker = " <-- MEILLEUR" if cs["is_most_complete"] else ""
            lines.append(f"    {cs['path']}")
            lines.append(f"      Score: {cs['score']} | Taille: {cs['size']} | Lignes: {cs['lines']} | Date: {cs['mtime']}{marker}")
        lines.append("")
        if cp.diff_summary:
            lines.append(f"  Differences: {cp.diff_summary}")
            lines.append("")
        lines.append("  Actions proposees (aucune execution sans confirmation):")
        for a in cp.actions:
            conf = " [CONFIRMATION REQUISE]" if a["requires_confirmation"] else ""
            lines.append(f"    - {a['action_type']}: {a['reason']}{conf}")
            if a.get("destination"):
                lines.append(f"      Destination: {a['destination']}")
        lines.append("")
        lines.append(f"  Recommandation IA: {cp.ai_recommendation}")
        lines.append("")

    lines.append("=" * 60)
    lines.append("AUCUNE ACTION N'A ETE EXECUTEE.")
    lines.append("Validez chaque action manuellement avant execution.")
    lines.append("=" * 60)
    return "\n".join(lines)