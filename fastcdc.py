"""FastCDC: Content-Defined Chunking pour la detection de fichiers partiellement dupliques.

FastCDC divise un fichier en chunks de taille variable basee sur le contenu,
permettant de detecter les parties communes entre des fichiers differents.
"""
from __future__ import annotations

import os
import hashlib
from typing import List, Tuple, Dict


# Parametres FastCDC
MIN_CHUNK_SIZE = 2 * 1024       # 2 Ko minimum
AVG_CHUNK_SIZE = 8 * 1024       # 8 Ko moyen
MAX_CHUNK_SIZE = 16 * 1024      # 16 Ko maximum
MASK = (1 << 13) - 1           # masque pour la detection de frontiere


def _rolling_hash(data: bytes, pos: int) -> int:
    """Calcule un hash glissant (Rabin fingerprint simplifie)."""
    h = 0
    for i in range(min(64, len(data) - pos)):
        h = (h * 31 + data[pos + i]) & 0xFFFFFFFF
    return h


def fastcdc_chunks(filepath: str, min_size: int = MIN_CHUNK_SIZE,
                   avg_size: int = AVG_CHUNK_SIZE, max_size: int = MAX_CHUNK_SIZE) -> List[Tuple[int, int, str]]:
    """Divise un fichier en chunks content-defined.

    Retourne une liste de (offset, length, hash) pour chaque chunk.
    """
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
        # Chercher la frontiere du chunk
        chunk_start = pos
        end = min(pos + max_size, size)

        # Minimum chunk size
        pos = min(pos + min_size, size)
        if pos >= size:
            # Dernier chunk
            chunk_data = data[chunk_start:size]
            chunk_hash = hashlib.md5(chunk_data).hexdigest()
            chunks.append((chunk_start, size - chunk_start, chunk_hash))
            break

        # Chercher la frontiere
        found = False
        for i in range(pos, end):
            if i >= size:
                break
            # Verifier si c'est une frontiere (rolling hash)
            if i >= chunk_start + min_size:
                h = _rolling_hash(data, i)
                if (h & MASK) == 0:
                    # Frontiere trouvee
                    chunk_data = data[chunk_start:i]
                    chunk_hash = hashlib.md5(chunk_data).hexdigest()
                    chunks.append((chunk_start, i - chunk_start, chunk_hash))
                    pos = i
                    found = True
                    break

        if not found:
            # Pas de frontiere trouvee: chunk de taille max
            chunk_end = min(chunk_start + max_size, size)
            chunk_data = data[chunk_start:chunk_end]
            chunk_hash = hashlib.md5(chunk_data).hexdigest()
            chunks.append((chunk_start, chunk_end - chunk_start, chunk_hash))
            pos = chunk_end

    return chunks


def compare_files_cdc(path1: str, path2: str) -> Dict:
    """Compare deux fichiers avec CDC et retourne le pourcentage de chunks communs."""
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