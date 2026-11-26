"""Detection du type de disque (HDD/SSD) et optimisation des parametres I/O."""
from __future__ import annotations

import os
import sys
from typing import Dict, Optional


def detect_disk_type(path: str) -> str:
    """Detecte si le disque contenant le chemin est un HDD ou un SSD.

    Retourne 'ssd', 'hdd' ou 'unknown'.
    """
    if os.name != "nt":
        return "unknown"
    try:
        # Extraire la lettre de disque
        drive = path[:2].upper() if len(path) >= 2 and path[1] == ":" else ""
        if not drive:
            return "unknown"

        # Utiliser WMI pour detecter le type de media
        import subprocess
        # MSFT_PhysicalDisk via PowerShell
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-PhysicalDisk | Select-Object DeviceId, MediaType, FriendlyName | ConvertTo-Json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return "unknown"

        import json
        disks = json.loads(result.stdout)
        if not isinstance(disks, list):
            disks = [disks]

        # Mapper les lettres de disque aux disques physiques
        # via Get-Partition
        cmd2 = [
            "powershell", "-NoProfile", "-Command",
            f"Get-Partition -DriveLetter {drive[0]} | Select-Object DiskNumber | ConvertTo-Json"
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
        if result2.returncode != 0:
            return "unknown"

        part = json.loads(result2.stdout)
        disk_num = part.get("DiskNumber") if isinstance(part, dict) else None
        if disk_num is None:
            return "unknown"

        for disk in disks:
            if str(disk.get("DeviceId")) == str(disk_num):
                media_type = disk.get("MediaType", "Unspecified")
                # MediaType peut etre un nombre ou une chaine
                if isinstance(media_type, str):
                    mt = media_type.upper()
                    if "SSD" in mt or "SCM" in mt:
                        return "ssd"
                    elif "HDD" in mt:
                        return "hdd"
                    # Unspecified: deviner par le nom
                    name = disk.get("FriendlyName", "").upper()
                    if "SSD" in name:
                        return "ssd"
                    # HDD connus
                    hdd_keywords = ["TOSHIBA MQ", "SEAGATE", "WD", "HGST", "HITACHI", "MQ01", "ST1000", "ST2000"]
                    if any(kw in name for kw in hdd_keywords):
                        return "hdd"
                    return "unknown"
                else:
                    if media_type == 4 or media_type == 5:
                        return "ssd"
                    elif media_type == 3:
                        return "hdd"
                    return "unknown"
    except Exception:
        pass
    return "unknown"


def optimal_io_threads(path: str) -> int:
    """Retourne le nombre optimal de threads I/O pour un chemin donne."""
    disk_type = detect_disk_type(path)
    if disk_type == "ssd":
        return 16
    elif disk_type == "hdd":
        return 2
    else:
        return 4


def optimal_io_threads_multi(paths: list) -> int:
    """Retourne le nombre optimal de threads I/O pour plusieurs chemins."""
    types = set(detect_disk_type(p) for p in paths)
    if "hdd" in types and "ssd" not in types:
        return 2  # Tous HDD
    elif "ssd" in types and "hdd" not in types:
        return 16  # Tous SSD
    else:
        return 4  # Mixte ou inconnu