"""Comparaison de rapports Markdown et fichiers texte.

Compare les fichiers .md (et autres fichiers texte) pour:
- Detecter les doublons exacts (meme contenu)
- Detecter les fichiers similaires (sections communes)
- Identifier les differences de contenu
- Proposer de merger les rapports
"""
from __future__ import annotations

import os
import re
import difflib
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def read_text_file(path: str, max_bytes: int = 10 * 1024 * 1024) -> Optional[str]:
    """Lit un fichier texte (max 10 Mo)."""
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, IOError, UnicodeDecodeError):
        return None


def extract_md_sections(content: str) -> Dict[str, str]:
    """Extrait les sections d'un fichier Markdown (par headers)."""
    sections = {}
    current_header = "preamble"
    current_content = []

    for line in content.splitlines():
        if line.startswith("#"):
            if current_content:
                sections[current_header] = "\n".join(current_content).strip()
            current_header = line.strip()
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections[current_header] = "\n".join(current_content).strip()

    return sections


def compare_md_files(path1: str, path2: str) -> Dict:
    """Compare deux fichiers Markdown et retourne un rapport detaille."""
    content1 = read_text_file(path1)
    content2 = read_text_file(path2)

    if content1 is None or content2 is None:
        return {"error": "Impossible de lire un des fichiers (binaire ou trop gros)"}

    result = {
        "path1": path1,
        "path2": path2,
        "identical": content1 == content2,
        "size1": len(content1),
        "size2": len(content2),
        "lines1": content1.count("\n") + 1,
        "lines2": content2.count("\n") + 1,
    }

    if content1 == content2:
        result["diff_summary"] = "Contenus identiques."
        result["similarity"] = 1.0
        return result

    # Similarite globale
    similarity = difflib.SequenceMatcher(None, content1, content2).ratio()
    result["similarity"] = round(similarity, 4)

    # Sections communes
    sections1 = extract_md_sections(content1)
    sections2 = extract_md_sections(content2)

    common_sections = set(sections1.keys()) & set(sections2.keys())
    only_in_1 = set(sections1.keys()) - set(sections2.keys())
    only_in_2 = set(sections2.keys()) - set(sections1.keys())

    result["common_sections"] = sorted(common_sections)
    result["sections_only_in_1"] = sorted(only_in_1)
    result["sections_only_in_2"] = sorted(only_in_2)

    # Diff unifie (limite a 50 lignes)
    diff = list(difflib.unified_diff(
        content1.splitlines(keepends=True),
        content2.splitlines(keepends=True),
        fromfile=os.path.basename(path1),
        tofile=os.path.basename(path2),
        lineterm="",
    ))
    result["unified_diff"] = "\n".join(diff[:50])
    result["diff_lines"] = len(diff)

    # Resume
    parts = []
    parts.append(f"Similarite: {similarity:.1%}")
    if common_sections:
        parts.append(f"Sections communes: {len(common_sections)}")
    if only_in_1:
        parts.append(f"Sections uniquement dans {os.path.basename(path1)}: {len(only_in_1)}")
    if only_in_2:
        parts.append(f"Sections uniquement dans {os.path.basename(path2)}: {len(only_in_2)}")
    result["diff_summary"] = "; ".join(parts)

    return result


def find_similar_md(files: List[str], threshold: float = 0.5) -> List[Tuple[str, str, float]]:
    """Trouve les paires de fichiers Markdown similaires (similarite >= threshold)."""
    md_files = [f for f in files if f.lower().endswith(".md")]
    pairs = []
    for i in range(len(md_files)):
        for j in range(i + 1, len(md_files)):
            content1 = read_text_file(md_files[i])
            content2 = read_text_file(md_files[j])
            if content1 is None or content2 is None:
                continue
            sim = difflib.SequenceMatcher(None, content1, content2).ratio()
            if sim >= threshold:
                pairs.append((md_files[i], md_files[j], round(sim, 4)))
    pairs.sort(key=lambda x: -x[2])
    return pairs


def merge_md_files(path1: str, path2: str, output_path: str) -> bool:
    """Fusionne deux fichiers Markdown en un seul (union des sections)."""
    content1 = read_text_file(path1)
    content2 = read_text_file(path2)
    if content1 is None or content2 is None:
        return False

    sections1 = extract_md_sections(content1)
    sections2 = extract_md_sections(content2)

    # Union des sections
    all_sections = {}
    all_headers = list(sections1.keys()) + [h for h in sections2.keys() if h not in sections1]

    for h in all_headers:
        if h in sections1 and h in sections2:
            # Fusionner le contenu (garder le plus long)
            if len(sections1[h]) >= len(sections2[h]):
                all_sections[h] = sections1[h]
            else:
                all_sections[h] = sections2[h]
        elif h in sections1:
            all_sections[h] = sections1[h]
        else:
            all_sections[h] = sections2[h]

    # Ecrire le resultat
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for h, content in all_sections.items():
                if h != "preamble":
                    f.write(h + "\n\n")
                f.write(content + "\n\n")
        return True
    except (OSError, IOError):
        return False