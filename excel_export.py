"""Export Excel avec graphiques pour le plan de comparaison."""
from __future__ import annotations

import os
import json

from pathlib import Path
from typing import Any

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


def export_excel(plan, out_dir: Path) -> Path:
    """Exporte le plan en fichier Excel avec plusieurs feuilles."""
    if not HAS_OPENPYXL:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"report_{ts}.xlsx"

    wb = openpyxl.Workbook()

    # Feuille 1: Resume
    ws = wb.active
    ws.title = "Resume"
    ws.append(["Metrique", "Valeur"])
    for k, v in plan.summary.items():
        if isinstance(v, (list, dict, tuple)):
            v = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v)
        ws.append([k, v])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 40

    # Feuille 2: Doublons
    ws2 = wb.create_sheet("Doublons")
    ws2.append(["Groupe", "Taille", "Copies", "Hash", "Cross-drive", "Octets gaspilles", "Fichiers"])
    for g in plan.duplicate_groups:
        ws2.append([
            g["key"][:16], g["size"], g["count"], g.get("hash", ""),
            g.get("cross_drive", False), g["wasted_bytes"],
            " | ".join(f["path"] for f in g["files"]),
        ])
    for col in "ABCDEFG":
        for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row):
            for cell in row:
                if cell.value is None:
                    cell.value = ""

    # Feuille 3: Fichiers uniques
    ws3 = wb.create_sheet("Uniques")
    ws3.append(["Chemin", "Racine", "Disque", "Taille", "Raison"])
    for u in plan.unique_files:
        ws3.append([u["path"], u["root"], u["drive"], u["size"], u["reason"]])
    for col in "ABCDE":
        ws3.column_dimensions[col].width = 30

    # Feuille 4: Top gros fichiers
    ws4 = wb.create_sheet("Top gros")
    ws4.append(["Chemin", "Racine", "Disque", "Taille"])
    for f in plan.top_largest:
        ws4.append([f["path"], f["root"], f["drive"], f["size"]])
    for col in "ABCD":
        ws4.column_dimensions[col].width = 30

    # Feuille 5: Par extension
    ws5 = wb.create_sheet("Extensions")
    ws5.append(["Extension", "Fichiers", "Taille"])
    for e in plan.by_extension:
        ws5.append([e["ext"], e["count"], e["size"]])
    for col in "ABC":
        ws5.column_dimensions[col].width = 20

    # Feuille 6: Dossiers vides
    ws6 = wb.create_sheet("Dossiers vides")
    ws6.append(["Chemin"])
    for d in plan.empty_dirs:
        ws6.append([d])
    ws6.column_dimensions["A"].width = 60

    # Feuille 7: Liens casses
    ws7 = wb.create_sheet("Liens casses")
    ws7.append(["Chemin"])
    for l in plan.broken_symlinks:
        ws7.append([l])
    ws7.column_dimensions["A"].width = 60

    wb.save(path)
    return path
