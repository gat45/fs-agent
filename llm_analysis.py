"""Analyse IA des differences de contenu entre fichiers via OpenCode.

Utilise la CLI OpenCode (opencode run) pour analyser les differences
et proposer des fusions intelligentes. Ne fait aucune action sans confirmation.
"""
from __future__ import annotations

import os
import json
import subprocess
import shutil
from pathlib import Path
from typing import List, Dict, Optional

# Verifier si OpenCode est disponible
OPENCODE_PATH = shutil.which("opencode")
HAS_OPENCODE = OPENCODE_PATH is not None


def generate_analysis_prompt(file1: str, file2: str, diff_summary: str) -> str:
    """Genere un prompt pour l'IA pour analyser les differences."""
    content1 = _read_file(file1)
    content2 = _read_file(file2)

    prompt = f"""Analyse les differences entre ces deux fichiers et propose une fusion intelligente.

Fichier 1: {file1}
Fichier 2: {file2}

Resume des differences: {diff_summary}

Contenu du fichier 1:
```
{content1[:2000]}
```

Contenu du fichier 2:
```
{content2[:2000]}
```

Questions:
1. Quel fichier est le plus complet et pourquoi?
2. Quelles informations sont presentes dans un fichier mais pas dans l'autre?
3. Propose une fusion qui conserve toutes les informations des deux fichiers.
4. Y a-t-il des contradictions entre les deux fichiers?

Reponds en francais, de maniere concise et structuree.
"""
    return prompt


def _read_file(path: str, max_bytes: int = 5000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except (OSError, IOError):
        return "[Impossible de lire le fichier]"


def analyze_with_opencode(prompt: str, model: str = None) -> Optional[str]:
    """Analyse avec OpenCode CLI."""
    if not HAS_OPENCODE:
        return "OpenCode non installe. Installez-le depuis https://opencode.ai"

    cmd = ["opencode", "run", prompt]
    if model:
        cmd.extend(["--model", model])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Erreur OpenCode (code {result.returncode}): {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Timeout: l'analyse a pris plus de 120 secondes."
    except Exception as e:
        return f"Erreur: {e}"


def generate_analysis_report(duplicate_groups: list, output_path: str, use_opencode: bool = False) -> str:
    """Genere un rapport d'analyse pour tous les groupes de doublons."""
    lines = []
    lines.append("# Rapport d'analyse - Consolidation de doublons")
    lines.append("")
    lines.append("Ce rapport contient les prompts et analyses pour chaque groupe de doublons.")
    lines.append("Aucune action n'est executee automatiquement.")
    lines.append("")

    for i, g in enumerate(duplicate_groups, 1):
        if g.get("is_hardlink_group"):
            continue
        files = g["files"]
        if len(files) < 2:
            continue

        mc = g.get("most_complete", {})
        lines.append(f"## Groupe {i}: {g['key'][:16]}...")
        lines.append(f"Meilleur: {mc.get('path', 'N/A')}")
        lines.append("")

        if len(files) >= 2:
            prompt = generate_analysis_prompt(files[0]["path"], files[1]["path"], g.get("diff_summary", ""))
            lines.append("### Prompt pour l'IA")
            lines.append("```")
            lines.append(prompt)
            lines.append("```")
            lines.append("")

            if use_opencode and HAS_OPENCODE:
                analysis = analyze_with_opencode(prompt)
                if analysis:
                    lines.append("### Analyse OpenCode")
                    lines.append(analysis)
                    lines.append("")

    content = "\n".join(lines)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
    return content