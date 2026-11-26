"""Hashing de fichiers: partial hash (rapide) puis full hash (SHA-256/BLAKE2).

Cache SQLite pour eviter de re-hasher des fichiers inchanges (cle: path+size+mtime).
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, "E:/python_packages")

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, List, Optional

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

from config import ScanConfig, CHUNK_SIZE, PARTIAL_HASH_BYTES

# Lock global pour la connexion SQLite partagee.
_DB_LOCK = threading.Lock()


def _partial_hash(path: str, algo: str = "sha256", nbytes: int = PARTIAL_HASH_BYTES) -> Optional[str]:
    """Hash rapide des premiers + derniers octets (blake2b/xxhash)."""
    try:
        size = os.path.getsize(path)
        h = hashlib.blake2b(digest_size=16) if algo == "blake2b" else hashlib.new(algo)
        # Utiliser le fast hash pour le partial
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
                    with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                        h = hashlib.new(algo)
                        # Lire par chunks depuis le mmap
                        pos = 0
                        while pos < size:
                            chunk_data = mm[pos:pos + chunk]
                            if not chunk_data:
                                break
                            h.update(chunk_data)
                            pos += chunk
                        return h.hexdigest()
            except (OSError, ValueError, mmap.error):
                pass  # Fallback sur la methode classique
        # Methode classique
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                h.update(data)
        return h.hexdigest()
    except (OSError, IOError):
        return None


class HashCache:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return sqlite3.connect(str(self.db_path), timeout=30)

    def _init(self):
        with _DB_LOCK:
            try:
                conn = self._conn()
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS file_hashes (
                            path TEXT PRIMARY KEY,
                            size INTEGER,
                            mtime REAL,
                            partial_hash TEXT,
                            full_hash TEXT,
                            algo TEXT,
                            updated_at REAL
                        )
                    """)
                    conn.commit()
                finally:
                    conn.close()
            except sqlite3.DatabaseError:
                # DB corrompue: supprimer et recreer
                try:
                    self.db_path.unlink(missing_ok=True)
                    for suffix in ("-wal", "-shm"):
                        p = self.db_path.with_suffix(self.db_path.suffix + suffix)
                        p.unlink(missing_ok=True)
                except OSError:
                    pass
                conn = self._conn()
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS file_hashes (
                            path TEXT PRIMARY KEY,
                            size INTEGER,
                            mtime REAL,
                            partial_hash TEXT,
                            full_hash TEXT,
                            algo TEXT,
                            updated_at REAL
                        )
                    """)
                    conn.commit()
                finally:
                    conn.close()

    def get(self, path: str, size: int, mtime: float) -> Optional[dict]:
        try:
            with _DB_LOCK:
                conn = self._conn()
                try:
                    cur = conn.execute(
                        "SELECT partial_hash, full_hash, algo FROM file_hashes WHERE path=? AND size=? AND mtime=?",
                        (path, size, mtime),
                    )
                    row = cur.fetchone()
                    if row:
                        return {"partial_hash": row[0], "full_hash": row[1], "algo": row[2]}
                    return None
                finally:
                    conn.close()
        except sqlite3.DatabaseError:
            self._init()
            return None

    def put(self, path: str, size: int, mtime: float, partial_hash: Optional[str],
            full_hash: Optional[str], algo: str):
        import time
        try:
            with _DB_LOCK:
                conn = self._conn()
                try:
                    conn.execute("""
                        INSERT INTO file_hashes (path, size, mtime, partial_hash, full_hash, algo, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            size=excluded.size, mtime=excluded.mtime,
                            partial_hash=excluded.partial_hash, full_hash=excluded.full_hash,
                            algo=excluded.algo, updated_at=excluded.updated_at
                    """, (path, size, mtime, partial_hash, full_hash, algo, time.time()))
                    conn.commit()
                finally:
                    conn.close()
        except sqlite3.DatabaseError:
            self._init()

    def stats(self) -> dict:
        with _DB_LOCK:
            conn = self._conn()
            try:
                cur = conn.execute("SELECT COUNT(*) FROM file_hashes")
                n = cur.fetchone()[0]
                return {"cached_entries": n, "db_path": str(self.db_path)}
            finally:
                conn.close()


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
        cache.put(path, size, mtime, entry.partial_hash, entry.full_hash, algo)
        return

    cached = cache.get(path, size, mtime)
    if cached and cached.get("algo") == algo:
        entry.partial_hash = cached.get("partial_hash")
        entry.full_hash = cached.get("full_hash")
        # Si full_hash manquant mais partial present, completer
        if cfg.compute_hash and not entry.full_hash:
            entry.full_hash = _full_hash(path, algo)
            cache.put(path, size, mtime, entry.partial_hash, entry.full_hash, algo)
        return

    # Partial hash (rapide) - utiliser blake2b/xxhash
    if cfg.partial_hash_first and size >= PARTIAL_HASH_BYTES * 2:
        entry.partial_hash = _partial_hash(path, "blake2b")
    elif cfg.partial_hash_first:
        entry.partial_hash = None
    else:
        entry.partial_hash = None

    # Full hash (si demande)
    if cfg.compute_hash:
        # Optimisation: si partial hash unique dans son groupe taille, on pourrait
        # eviter le full hash. Ici on laisse le comparator decider; on calcule
        # toujours le full hash pour les fichiers <= seuil raisonnable.
        entry.full_hash = _full_hash(path, algo)
    else:
        entry.full_hash = None

    cache.put(path, size, mtime, entry.partial_hash, entry.full_hash, algo)


def hash_entries(entries: List, cfg: ScanConfig,
                 progress_cb: Optional[Callable[[int], None]] = None) -> None:
    """Hash une liste de FileEntry en parallele avec cache.

    Optimisations:
    - Bloom filter: ne hashe que les fichiers dont la taille est partagee.
    - Incremental: utilise le cache SQLite pour eviter de re-hasher.
    """
    cache = HashCache(cfg.resolved_cache_db())
    # Limiter les threads I/O pour eviter de saturer le disque
    workers = max(1, min(getattr(cfg, 'io_threads', 2), cfg.workers))
    throttle = getattr(cfg, 'io_throttle_ms', 0) / 1000.0 if getattr(cfg, 'io_throttle_ms', 0) > 0 else 0

    # Bloom filter sur les tailles
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
            import time
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
