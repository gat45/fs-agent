"""FastCDC: Content-Defined Chunking pour la detection de fichiers partiellement dupliques.

Implementation conforme a FastCDC (Xia et al., 2016) avec:
- Table Gear pour le rolling hash
- Chunking content-defined avec bornes min/avg/max
- Hash cryptographique (SHA-256) pour les chunks
- Preservation des occurrences dans la comparaison
"""
from __future__ import annotations

import os
import hashlib
import struct
from typing import List, Tuple, Dict, Optional


# Table Gear (64-bit random values) pour le rolling hash
# Generee une fois et reutilisee
_GEAR_TABLE = None


def _get_gear_table() -> List[int]:
    """Genere la table Gear (64-bit)."""
    global _GEAR_TABLE
    if _GEAR_TABLE is not None:
        return _GEAR_TABLE
    import random
    random.seed(42)  # Deterministe pour la reproductibilite
    _GEAR_TABLE = [random.getrandbits(64) for _ in range(256)]
    return _GEAR_TABLE


# Parametres FastCDC
MIN_CHUNK_SIZE = 4 * 1024       # 4 Ko minimum
AVG_CHUNK_SIZE = 8 * 1024       # 8 Ko moyen
MAX_CHUNK_SIZE = 16 * 1024      # 16 Ko maximum
MASK_S = (1 << 13) - 1         # masque pour la detection de frontiere (avg_size ~ 8Ko)
MASK_L = (1 << 14) - 1         # masque plus large pour les gros chunks


def _rolling_hash_gear(data: bytes, pos: int, gear: List[int]) -> int:
    """Calcule le hash Rabin (Gear-based) sur une fenetre."""
    h = 0
    for i in range(min(64, len(data) - pos)):
        h = ((h << 1) + gear[data[pos + i]]) & ((1 << 64) - 1)
    return h


def fastcdc_chunks(filepath: str, min_size: int = MIN_CHUNK_SIZE,
                   avg_size: int = AVG_CHUNK_SIZE, max_size: int = MAX_CHUNK_SIZE) -> List[Tuple[int, int, str]]:
    """Divise un fichier en chunks content-defined selon FastCDC.

    Retourne une liste de (offset, length, sha256_hash) pour chaque chunk.
    """
    try:
        size = os.path.getsize(filepath)
    except OSError:
        return []

    if size == 0:
        return []

    gear = _get_gear_table()
    chunks = []
    pos = 0

    with open(filepath, "rb") as f:
        data = f.read()

    while pos < size:
        chunk_start = pos
        end = min(pos + max_size, size)
        search_start = min(pos + min_size, size)

        if search_start >= size:
            # Dernier chunk
            chunk_data = data[chunk_start:size]
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()
            chunks.append((chunk_start, size - chunk_start, chunk_hash))
            break

        # Phase 1: chercher avec le masque normal (avg_size)
        found = False
        for i in range(search_start, end):
            if i >= size:
                break
            h = _rolling_hash_gear(data, i, gear)
            if (h & MASK_S) == 0:
                chunk_data = data[chunk_start:i]
                chunk_hash = hashlib.sha256(chunk_data).hexdigest()
                chunks.append((chunk_start, i - chunk_start, chunk_hash))
                pos = i
                found = True
                break

        if not found:
            # Phase 2: chercher avec le masque large (max_size)
            for i in range(search_start, end):
                if i >= size:
                    break
                h = _rolling_hash_gear(data, i, gear)
                if (h & MASK_L) == 0:
                    chunk_data = data[chunk_start:i]
                    chunk_hash = hashlib.sha256(chunk_data).hexdigest()
                    chunks.append((chunk_start, i - chunk_start, chunk_hash))
                    pos = i
                    found = True
                    break

        if not found:
            # Pas de frontiere: chunk de taille max
            chunk_end = min(chunk_start + max_size, size)
            chunk_data = data[chunk_start:chunk_end]
            chunk_hash = hashlib.sha256(chunk_data).hexdigest()
            chunks.append((chunk_start, chunk_end - chunk_start, chunk_hash))
            pos = chunk_end

    return chunks


def compare_files_cdc(path1: str, path2: str) -> Dict:
    """Compare deux fichiers avec CDC et retourne le pourcentage de chunks communs.

    Utilise des compteurs (pas des ensembles) pour preserver les occurrences.
    """
    chunks1 = fastcdc_chunks(path1)
    chunks2 = fastcdc_chunks(path2)

    if not chunks1 or not chunks2:
        return {"similarity": 0.0, "common_chunks": 0, "total_chunks": 0,
                "chunks1": len(chunks1), "chunks2": len(chunks2)}

    # Compter les occurrences de chaque hash
    from collections import Counter
    counts1 = Counter(c[2] for c in chunks1)
    counts2 = Counter(c[2] for c in chunks2)

    # Chunks communs: min des occurrences
    common_hashes = set(counts1.keys()) & set(counts2.keys())
    common_count = sum(min(counts1[h], counts2[h]) for h in common_hashes)

    # Total: union des occurrences
    total_count = sum(counts1.values()) + sum(counts2.values()) - common_count

    similarity = common_count / total_count if total_count > 0 else 0.0

    return {
        "similarity": round(similarity, 4),
        "common_chunks": common_count,
        "total_chunks": total_count,
        "chunks1": len(chunks1),
        "chunks2": len(chunks2),
        "size1": os.path.getsize(path1),
        "size2": os.path.getsize(path2),
        "occurrences1": dict(counts1),
        "occurrences2": dict(counts2),
    }


def find_partial_duplicates(files: List[str], threshold: float = 0.5) -> List[Dict]:
    """Trouve les fichiers partiellement dupliques (similarite >= threshold)."""
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