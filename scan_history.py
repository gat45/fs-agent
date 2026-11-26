"""Memoire persistante: historique des scans et comparaison temporelle.

Stocke les resultats de chaque scan dans SQLite pour:
- Comparer l'etat actuel avec un scan precedent
- Suivre les fichiers ajoutes/supprimes/modifies
- Detecter les changements entre les scans
"""
from __future__ import annotations

import os
import sqlite3
import threading
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from config import CACHE_DIR

_DB_LOCK = threading.Lock()


class ScanHistory:
    """Historique persistant des scans."""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = CACHE_DIR / "scan_history.sqlite"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return sqlite3.connect(str(self.db_path), timeout=30)

    def _init(self):
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS scans (
                        scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL,
                        roots TEXT,
                        total_files INTEGER,
                        total_size INTEGER,
                        total_dirs INTEGER,
                        errors INTEGER,
                        duration_sec REAL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS scan_files (
                        scan_id INTEGER,
                        path TEXT,
                        root TEXT,
                        drive TEXT,
                        size INTEGER,
                        mtime REAL,
                        ext TEXT,
                        full_hash TEXT,
                        partial_hash TEXT,
                        FOREIGN KEY(scan_id) REFERENCES scans(scan_id)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_scan_files_path ON scan_files(path)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_scan_files_scan_id ON scan_files(scan_id)
                """)
                conn.commit()
            finally:
                conn.close()

    def save_scan(self, scan_result, duration_sec: float = 0) -> int:
        """Sauvegarde un scan et retourne son ID."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                cur = conn.execute("""
                    INSERT INTO scans (timestamp, roots, total_files, total_size, total_dirs, errors, duration_sec)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    time.time(),
                    json.dumps(sorted(scan_result.roots)),
                    scan_result.total_files,
                    scan_result.total_size,
                    len(scan_result.dirs),
                    len(scan_result.errors),
                    duration_sec,
                ))
                scan_id = cur.lastrowid
                # Inserer les fichiers
                for f in scan_result.files:
                    conn.execute("""
                        INSERT INTO scan_files (scan_id, path, root, drive, size, mtime, ext, full_hash, partial_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        scan_id, f.path, f.root, f.drive, f.size, f.mtime, f.ext,
                        getattr(f, 'full_hash', None), getattr(f, 'partial_hash', None),
                    ))
                conn.commit()
                return scan_id
            finally:
                conn.close()

    def get_last_scan(self, roots: List[str] = None) -> Optional[Dict]:
        """Recupere le dernier scan (optionnellement filtre par racines)."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                if roots:
                    cur = conn.execute(
                        "SELECT * FROM scans WHERE roots=? ORDER BY timestamp DESC LIMIT 1",
                        (json.dumps(sorted(roots)),),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM scans ORDER BY timestamp DESC LIMIT 1"
                    )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "scan_id": row[0],
                    "timestamp": row[1],
                    "roots": json.loads(row[2]),
                    "total_files": row[3],
                    "total_size": row[4],
                    "total_dirs": row[5],
                    "errors": row[6],
                    "duration_sec": row[7],
                }
            finally:
                conn.close()

    def get_scan_files(self, scan_id: int) -> List[Dict]:
        """Recupere les fichiers d'un scan."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT path, root, drive, size, mtime, ext, full_hash, partial_hash FROM scan_files WHERE scan_id=?",
                    (scan_id,),
                )
                return [
                    {"path": r[0], "root": r[1], "drive": r[2], "size": r[3],
                     "mtime": r[4], "ext": r[5], "full_hash": r[6], "partial_hash": r[7]}
                    for r in cur.fetchall()
                ]
            finally:
                conn.close()

    def compare_scans(self, old_scan_id: int, new_scan_id: int) -> Dict:
        """Compare deux scans et retourne les changements."""
        old_files = {f["path"]: f for f in self.get_scan_files(old_scan_id)}
        new_files = {f["path"]: f for f in self.get_scan_files(new_scan_id)}

        added = []
        removed = []
        modified = []
        unchanged = []

        for path, f in new_files.items():
            if path not in old_files:
                added.append(f)
            else:
                old = old_files[path]
                # Comparer size, mtime ET hash (si disponible)
                changed = False
                if old["size"] != f["size"] or old["mtime"] != f["mtime"]:
                    changed = True
                elif old.get("full_hash") and f.get("full_hash") and old["full_hash"] != f["full_hash"]:
                    changed = True
                elif old.get("partial_hash") and f.get("partial_hash") and old["partial_hash"] != f["partial_hash"]:
                    changed = True
                if changed:
                    modified.append({"old": old, "new": f})
                else:
                    unchanged.append(f)

        for path, f in old_files.items():
            if path not in new_files:
                removed.append(f)

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "unchanged_count": len(unchanged),
            "old_total": len(old_files),
            "new_total": len(new_files),
        }

    def list_scans(self, limit: int = 20) -> List[Dict]:
        """Liste les scans recents."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT scan_id, timestamp, roots, total_files, total_size, total_dirs, errors, duration_sec FROM scans ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
                return [
                    {"scan_id": r[0], "timestamp": r[1], "roots": json.loads(r[2]),
                     "total_files": r[3], "total_size": r[4], "total_dirs": r[5],
                     "errors": r[6], "duration_sec": r[7]}
                    for r in cur.fetchall()
                ]
            finally:
                conn.close()

    def get_scan_by_id(self, scan_id: int) -> Optional[Dict]:
        """Recupere un scan par son ID."""
        with _DB_LOCK:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT scan_id, timestamp, roots, total_files, total_size, total_dirs, errors, duration_sec FROM scans WHERE scan_id=?",
                    (scan_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {"scan_id": row[0], "timestamp": row[1], "roots": json.loads(row[2]),
                        "total_files": row[3], "total_size": row[4], "total_dirs": row[5],
                        "errors": row[6], "duration_sec": row[7]}
            finally:
                conn.close()
