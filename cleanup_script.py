"""Generation de scripts de nettoyage a partir du plan."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List


def generate_cleanup_script(plan, out_dir: Path, fmt: str = "bat") -> Path:
    """Genere un script de nettoyage (bat ou sh) pour supprimer les doublons."""
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if fmt == "bat":
        path = out_dir / f"cleanup_{ts}.bat"
        lines = ["@echo off", "REM Script de nettoyage genere par fs-agent", "REM ATTENTION: verifiez avant d'executer!", ""]
        # Supprimer les doublons (garder le premier de chaque groupe)
        for g in plan.duplicate_groups:
            if g.get("is_hardlink_group"):
                continue
            files = [f["path"] for f in g["files"]]
            # Garder le premier, supprimer les autres
            for f in files[1:]:
                lines.append(f'del /f /q "{f}"')
        # Supprimer les dossiers vides
        for d in plan.empty_dirs:
            lines.append(f'rmdir "{d}" 2>nul')
        lines.append("")
        lines.append("echo Nettoyage termine.")
        lines.append("pause")
    else:
        path = out_dir / f"cleanup_{ts}.sh"
        lines = ["#!/bin/bash", "# Script de nettoyage genere par fs-agent", "# ATTENTION: verifiez avant d'executer!", ""]
        for g in plan.duplicate_groups:
            if g.get("is_hardlink_group"):
                continue
            files = [f["path"] for f in g["files"]]
            for f in files[1:]:
                lines.append(f'rm -f "{f}"')
        for d in plan.empty_dirs:
            lines.append(f'rmdir "{d}" 2>/dev/null')
        lines.append("")
        lines.append('echo "Nettoyage termine."')

    path.write_text("\n".join(lines), encoding="utf-8")
    if fmt != "bat":
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
    return path


def generate_hardlink_script(plan, out_dir: Path) -> Path:
    """Genere un script pour remplacer les doublons par des hardlinks."""
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"hardlink_{ts}.bat"
    lines = ["@echo off", "REM Remplace les doublons par des hardlinks (Windows)", "REM ATTENTION: verifiez avant d'executer!", ""]
    for g in plan.duplicate_groups:
        if g.get("is_hardlink_group"):
            continue
        files = [f["path"] for f in g["files"]]
        if len(files) < 2:
            continue
        orig = files[0]
        for dup in files[1:]:
            lines.append(f'del /f /q "{dup}"')
            lines.append(f'mklink /H "{dup}" "{orig}"')
    lines.append("")
    lines.append("echo Hardlink termine.")
    lines.append("pause")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
