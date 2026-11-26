"""Hashing de fichiers: partial hash (rapide) puis full hash (SHA-256/BLAKE2).

Cache SQLite pour eviter de re-hasher des fichiers inchanges (cle: path+size+mtime+ctime).
Utilise une connexion persistante pour la performance.
"""
from __future__ import annotations

import hashlib
import os
import sys
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time
from typing import Callable, List, Optional

sys.path.insert(0, "E:/python_packages")

from config import ScanConfig, CHUNK_SIZE, PARTIAL_HASH_BYTES

# Essayer d'utiliser xxhash si disponible, sinon blake2b (stdlib, rapide)
try:
    import xxhash as _xxh
    def _fast_hash(data: bytes) -> str:
        return _xxh.xxh64(data).hexdigest()
    FAST_HASH_NAME = "xxh64"
except ImportError:
    import hashlib as _hl
    def _fast_hash(data: bytes) -> str:
        return _hl.blake2b(data, digest_size=8).hexdigest()
    FAST_HASH_NAME = "blake2b"


_DB_LOCK = threading.Lock()
_PERSISTENT_CONN = None
_CONN_LOCK = threading.Lock()


def _get_conn(db_path: Path):
    """Retourne une connexion persistante (thread-safe via lock)."""
    global _PERSISTENT_CONN
    with _CONN_LOCK:
        if _PERSISTENT_CONN is None:
            _PERSISTENT_CONN = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
            _PERSISTENT_CONN.execute("PRAGMA journal_mode=WAL")
        return _PERSISTENT_CONN


def _partial_hash(path: str, nbytes: int = PARTIAL_HASH_BYTES) -> Optional[str]:
    """Hash rapide des premiers + derniers octets."""
    try:
        size = os.path.getsize(path)
        h = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as f:
            head = f.read(min(nbytes, size))
            h.update(head)
            if size > nbytes:
                f.seek(max(0, size - nbytes))
                tail = f.read(nbytes)
                h.update(tail)
            h.update(str(size).encode())
        return h.hexdigest()
    except (OSError, IOError):
        return None


def _full_hash(path: str, algo: str = "sha256", chunk: int = CHUNK_SIZE) -> Optional[str]:
    """Full hash avec memory-mapped I/O pour les gros fichiers."""
    try:
        size = os.path.getsize(path)
        # Memory-mapped pour les gros fichiers (> 1 Mo)
        if size > 1024 * 1024:
            try:
                import mmap
                with open(path, "rb") as f:
                    # Verifier la taille avant et apres (atomicite)
                    st_before = os.fstat(f.fileno())
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        h = hashlib.new(algo)
                        pos = 0
                        while pos < size:
                            chunk_data = mm[pos:pos + chunk]
                            if not chunk_data:
                                break
                            h.update(chunk_data)
                            pos += chunk
                        st_after = os.fstat(f.fileno())
                        # Verifier que le fichier n'a pas change
                        if st_before.st_size != st_after.st_size or st_before.st_mtime != st_after.st_mtime:
                            return None  # Fichier modifie pendant la lecture
                        return h.hexdigest()
            except (OSError, ValueError, mmap.error):
                pass
        # Methode classique
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            st_before = os.fstat(f.fileno())
            while True:
                data = f.read(chunk)
                if not data:
                    break
                h.update(data)
            st_after = os.fstat(f.fileno())
            if st_before.st_size != st_after.st_size or st_before.st_mtime != st_after.st_mtime:
                return None
        return h.hexdigest()
    except (OSError, IOError):
        return None


class HashCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return _get_conn(self.db_path)

    def _init(self):
        with _DB_LOCK:
            conn = self._conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS file_hashes (
                        path TEXT PRIMARY KEY,
                        size INTEGER,
                        mtime REAL,
                        ctime REAL,
                        partial_hash TEXT,
                        full_hash TEXT,
                        algo TEXT,
                        updated_at REAL
                    )
                """)
                conn.commit()
            except Exception:
                pass

    def get(self, path: str, size: int, mtime: float, ctime: float = 0) -> Optional[dict]:
        try:
            with _DB_LOCK:
                conn = self._conn()
                cur = conn.execute(
                    "SELECT partial_hash, full_hash, algo, ctime FROM file_hashes WHERE path=? AND size=? AND mtime=?",
                    (path, size, mtime),
                )
                row = cur.fetchone()
                if row:
                    # Verifier le ctime si disponible
                    if ctime > 0 and row[3] > 0 and row[3] != ctime:
                        return None  # Fichier modifie
                    return {"partial_hash": row[0], "full_hash": row[1], "algo": row[2]}
                return None
        except Exception:
            return None

    def put(self, path: str, size: int, mtime: float, partial_hash: Optional[str],
            full_hash: Optional[str], algo: str, ctime: float = 0):
        try:
            with _DB_LOCK:
                conn = self._conn()
                conn.execute("""
                    INSERT INTO file_hashes (path, size, mtime, ctime, partial_hash, full_hash, algo, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        size=excluded.size, mtime=excluded.mtime, ctime=excluded.ctime,
                        partial_hash=excluded.partial_hash, full_hash=excluded.full_hash,
                        algo=excluded.algo, updated_at=excluded.updated_at
                """, (path, size, mtime, ctime, partial_hash, full_hash, algo, time.time()))
                conn.commit()
        except Exception:
            pass

    def stats(self) -> dict:
        try:
            with _DB_LOCK:
                conn = self._conn()
                cur = conn.execute("SELECT COUNT(*) FROM file_hashes")
                n = cur.fetchone()[0]
                return {"cached_entries": n, "db_path": str(self.db_path)}
        except Exception:
            return {"cached_entries": 0, "db_path": str(self.db_path)}


def hash_file(entry, cfg: ScanConfig, cache: HashCache) -> None:
    """Remplit entry.partial_hash et entry.full_hash en place."""
    path = entry.path
    size = entry.size
    mtime = entry.mtime
    algo = cfg.hash_algorithm

    # Cas fichier vide
    if size == 0:
        entry.partial_hash = "empty"
        entry.full_hash = "empty"
        try:
            st = os.stat(path)
            cache.put(path, size, mtime, entry.partial_hash, entry.full_hash, algo, st.st_ctime)
        except OSError:
            pass
        return

    # Obtenir le ctime
    try:
        st = os.stat(path)
        ctime = st.st_ctime
    except OSError:
        ctime = 0

    cached = cache.get(path, size, mtime, ctime)
    if cached and cached.get("algo") == algo:
        entry.partial_hash = cached.get("partial_hash")
        entry.full_hash = cached.get("full_hash")
        if cfg.compute_hash and not entry.full_hash:
            entry.full_hash = _full_hash(path, algo)
            cache.put(path, size, mtime, entry.partial_hash, entry.full_hash, algo, ctime)
        return

    # Partial hash (rapide)
    if cfg.partial_hash_first and size >= PARTIAL_HASH_BYTES * 2:
        entry.partial_hash = _partial_hash(path)
    else:
        entry.partial_hash = None

    # Full hash
    if cfg.compute_hash:
        entry.full_hash = _full_hash(path, algo)
    else:
        entry.full_hash = None

    cache.put(path, size, mtime, entry.partial_hash, entry.full_hash, algo, ctime)


def hash_entries(entries: List, cfg: ScanConfig,
                 progress_cb: Optional[Callable[[int], None]] = None) -> None:
    """Hash une liste de FileEntry en parallele avec cache."""
    cache = HashCache(cfg.resolved_cache_db())
    workers = max(1, min(getattr(cfg, 'io_threads', 2), cfg.workers))
    throttle = getattr(cfg, 'io_throttle_ms', 0) / 1000.0 if getattr(cfg, 'io_throttle_ms', 0) > 0 else 0

    from bloom import filter_unique_sizes
    hashable = filter_unique_sizes(entries)
    hashable_set = {id(e) for e in hashable}

    def _work(e):
        if id(e) not in hashable_set:
            e.partial_hash = None
            e.full_hash = None
            if progress_cb:
                progress_cb(1)
            return
        hash_file(e, cfg, cache)
        if throttle > 0:
            time.sleep(throttle)
        if progress_cb:
            progress_cb(1)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_work, e) for e in entries]
        for f in as_completed(futs):
            try:
                f.result()
            except Exception:
                pass

    # Batch commit: une seule transaction pour tous les fichiers
    try:
        with _DB_LOCK:
            conn = cache._conn()
            conn.commit()
    except Exception:
        pass