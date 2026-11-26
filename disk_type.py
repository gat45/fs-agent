"""Detection du type de disque (HDD/SSD) et optimisation des parametres I/O."""
from __future__ import annotations

import os
import subprocess
import json
from typing import Dict, Optional

# Cache pour detect_disk_type
_DISK_TYPE_CACHE = {}


def detect_disk_type(path: str) -> str:
    """Detecte si le disque contenant le chemin est un HDD ou un SSD.

    Resultat mis en cache pour eviter les appels repetes a PowerShell.
    """
    if os.name != "nt":
        return "unknown"
    try:
        drive = path[:2].upper() if len(path) >= 2 and path[1] == ":" else ""
        if not drive:
            return "unknown"

        # Verifier le cache
        if drive in _DISK_TYPE_CACHE:
            return _DISK_TYPE_CACHE[drive]

        # Utiliser WMI pour detecter le type de media
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-PhysicalDisk | Select-Object DeviceId, MediaType, FriendlyName | ConvertTo-Json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            _DISK_TYPE_CACHE[drive] = "unknown"
            return "unknown"

        disks = json.loads(result.stdout)
        if not isinstance(disks, list):
            disks = [disks]

        # Mapper les lettres de disque aux disques physiques
        cmd2 = [
            "powershell", "-NoProfile", "-Command",
            f"Get-Partition -DriveLetter {drive[0]} | Select-Object DiskNumber | ConvertTo-Json"
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=10)
        if result2.returncode != 0:
            _DISK_TYPE_CACHE[drive] = "unknown"
            return "unknown"

        part = json.loads(result2.stdout)
        disk_num = part.get("DiskNumber") if isinstance(part, dict) else None
        if disk_num is None:
            _DISK_TYPE_CACHE[drive] = "unknown"
            return "unknown"

        for disk in disks:
            if str(disk.get("DeviceId")) == str(disk_num):
                media_type = disk.get("MediaType", "Unspecified")
                if isinstance(media_type, str):
                    mt = media_type.upper()
                    if "SSD" in mt or "SCM" in mt:
                        result = "ssd"
                    elif "HDD" in mt:
                        result = "hdd"
                    else:
                        name = disk.get("FriendlyName", "").upper()
                        if "SSD" in name:
                            result = "ssd"
                        elif any(kw in name for kw in ["TOSHIBA MQ", "SEAGATE", "WD", "HGST", "HITACHI", "MQ01", "ST1000", "ST2000"]):
                            result = "hdd"
                        else:
                            result = "unknown"
                else:
                    if media_type in (4, 5):
                        result = "ssd"
                    elif media_type == 3:
                        result = "hdd"
                    else:
                        result = "unknown"
                _DISK_TYPE_CACHE[drive] = result
                return result

        _DISK_TYPE_CACHE[drive] = "unknown"
        return "unknown"
    except Exception:
        _DISK_TYPE_CACHE[drive] = "unknown"
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
        return 2
    elif "ssd" in types and "hdd" not in types:
        return 16
    else:
        return 4