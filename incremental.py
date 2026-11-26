"""Scan incrementiel: ne re-scanner que les dossiers modifies.

Cache de mtime par dossier dans SQLite. Si un dossier n'a pas change
(mtime identique), on le saute et on utilise le cache.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional, Dict, List, Set

_DB_LOCK = threading.Lock()


class DirCache:
    """Cache de metadonnees de dossiers (path -> mtime, file_count, total_size)."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return sqlite3.connect(str(self.db_path), timeout=30)

    def _init(self):
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS dir_cache (
                        path TEXT PRIMARY KEY,
                        mtime REAL,
                        file_count INTEGER,
                        total_size INTEGER,
                        scanned_at REAL
                    )
                """)
                conn.commit()
            finally:
                conn.close()

    def get(self, path: str) -> Optional[Dict]:
        with _DB_LOCK:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT mtime, file_count, total_size FROM dir_cache WHERE path=?",
                    (path,),
                )
                row = cur.fetchone()
                if row:
                    return {"mtime": row[0], "file_count": row[1], "total_size": row[2]}
                return None
            finally:
                conn.close()

    def put(self, path: str, mtime: float, file_count: int, total_size: int):
        import time
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("""
                    INSERT INTO dir_cache (path, mtime, file_count, total_size, scanned_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        mtime=excluded.mtime, file_count=excluded.file_count,
                        total_size=excluded.total_size, scanned_at=excluded.scanned_at
                """, (path, mtime, file_count, total_size, time.time()))
                conn.commit()
            finally:
                conn.close()

    def invalidate(self, path: str):
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM dir_cache WHERE path=?", (path,))
                conn.commit()
            finally:
                conn.close()

    def clear(self):
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("DELETE FROM dir_cache")
                conn.commit()
            finally:
                conn.close()


def get_changed_dirs(root: str, cache: DirCache) -> Set[str]:
    """Retourne l'ensemble des dossiers modifies depuis le dernier scan.

    Optimisation: ne fait qu'un seul os.walk et utilise le cache pour
    determiner quels dossiers ont change.
    """
    changed = set()
    try:
        for dirpath, dirnames, _ in os.walk(root):
            try:
                st = os.stat(dirpath)
                cached = cache.get(dirpath)
                if cached is None or cached["mtime"] != st.st_mtime:
                    changed.add(dirpath)
            except OSError:
                changed.add(dirpath)
    except Exception:
        pass
    return changed


def is_incremental_available(cache: DirCache) -> bool:
    """Verifie si un scan incrementiel est possible (cache non vide)."""
    with _DB_LOCK:
        conn = cache._conn()
        try:
            cur = conn.execute("SELECT COUNT(*) FROM dir_cache")
            n = cur.fetchone()[0]
            return n > 0
        finally:
            conn.close()