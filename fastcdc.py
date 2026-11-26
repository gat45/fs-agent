"""FastCDC: Content-Defined Chunking pour la detection de fichiers partiellement dupliques."""
from __future__ import annotations

import os
import hashlib
from typing import List, Tuple, Dict


MIN_CHUNK_SIZE = 64
AVG_CHUNK_SIZE = 256
MAX_CHUNK_SIZE = 1024
MASK = (1 << 5) - 1  # 1/32
WINDOW_SIZE = 32


def _rabin_hash(data: bytes, pos: int, window: int = WINDOW_SIZE) -> int:
    """Calcule un hash Rabin sur une fenetre de bytes."""
    h = 0
    base = 256
    mod = (1 << 31) - 1
    for i in range(window):
        if pos + i < len(data):
            h = (h * base + data[pos + i]) % mod
    return h


def fastcdc_chunks(filepath: str, min_size: int = MIN_CHUNK_SIZE,
                   avg_size: int = AVG_CHUNK_SIZE, max_size: int = MAX_CHUNK_SIZE) -> List[Tuple[int, int, str]]:
    try:
        size = os.path.getsize(filepath)
    except OSError:
        return []
    if size == 0:
        return []

    chunks = []
    pos = 0
    with open(filepath, "rb") as f:
        data = f.read()

    while pos < size:
        chunk_start = pos
        end = min(pos + max_size, size)
        search_start = min(pos + min_size, size)

        if search_start >= size:
            chunk_data = data[chunk_start:size]
            chunk_hash = hashlib.md5(chunk_data).hexdigest()
            chunks.append((chunk_start, size - chunk_start, chunk_hash))
            break

        found = False
        for i in range(search_start, end):
            if i >= size:
                break
            h = _rabin_hash(data, i)
            if (h & MASK) == 0:
                chunk_data = data[chunk_start:i]
                chunk_hash = hashlib.md5(chunk_data).hexdigest()
                chunks.append((chunk_start, i - chunk_start, chunk_hash))
                pos = i
                found = True
                break

        if not found:
            chunk_end = min(chunk_start + max_size, size)
            chunk_data = data[chunk_start:chunk_end]
            chunk_hash = hashlib.md5(chunk_data).hexdigest()
            chunks.append((chunk_start, chunk_end - chunk_start, chunk_hash))
            pos = chunk_end

    return chunks


def compare_files_cdc(path1: str, path2: str) -> Dict:
    chunks1 = fastcdc_chunks(path1)
    chunks2 = fastcdc_chunks(path2)
    if not chunks1 or not chunks2:
        return {"similarity": 0.0, "common_chunks": 0, "total_chunks": 0, "chunks1": len(chunks1), "chunks2": len(chunks2)}
    hashes1 = {c[2] for c in chunks1}
    hashes2 = {c[2] for c in chunks2}
    common = hashes1 & hashes2
    total = len(hashes1 | hashes2)
    similarity = len(common) / total if total > 0 else 0.0
    return {
        "similarity": round(similarity, 4),
        "common_chunks": len(common),
        "total_chunks": total,
        "chunks1": len(chunks1),
        "chunks2": len(chunks2),
        "size1": os.path.getsize(path1),
        "size2": os.path.getsize(path2),
    }


def find_partial_duplicates(files: List[str], threshold: float = 0.5) -> List[Dict]:
    results = []
    for i in range(len(files)):
        for j in range(i + 1, len(files)):
            try:
                cmp = compare_files_cdc(files[i], files[j])
                if cmp["similarity"] >= threshold:
                    results.append({
                        "file1": files[i],
                        "file2": files[j],
                        "similarity": cmp["similarity"],
                        "common_chunks": cmp["common_chunks"],
                        "total_chunks": cmp["total_chunks"],
                    })
            except Exception:
                pass
    results.sort(key=lambda x: -x["similarity"])
    return results