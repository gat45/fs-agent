"""Planification de scans automatiques (cron / Task Scheduler)."""
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

TASK_NAME = "FS-Agent Scan"


def create_windows_task(script_path: str, schedule: str = "daily", time: str = "02:00") -> bool:
    """Cree une tache planifiee Windows pour le scan."""
    if os.name != "nt":
        return False

    # Construire la commande schtasks
    cmd = [
        "schtasks", "/create",
        "/tn", TASK_NAME,
        "/tr", f'python "{script_path}" --all-drives --partial-only',
        "/sc", schedule,
        "/st", time,
        "/f",  # forcer si existe deja
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Tache planifiee creee: {TASK_NAME} ({schedule} a {time})")
            return True
        else:
            print(f"Erreur: {result.stderr}")
            return False
    except Exception as e:
        print(f"Erreur: {e}")
        return False


def delete_windows_task() -> bool:
    """Supprime la tache planifiee."""
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"Tache planifiee supprimee: {TASK_NAME}")
            return True
        return False
    except Exception as e:
        print(f"Erreur: {e}")
        return False


def list_windows_task() -> Optional[str]:
    """Liste la tache planifiee."""
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None