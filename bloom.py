"""Bloom filter probabiliste pour eviter de hasher les fichiers uniques.

Utilise un bit array et plusieurs fonctions de hash pour tester rapidement
si une taille de fichier a deja ete vue. Si la taille n'a pas ete vue, le
fichier ne peut pas etre un doublon (pas besoin de hasher).
"""
from __future__ import annotations

import hashlib
from typing import Set


class BloomFilter:
    """Bloom filter simple pour les tailles de fichiers."""

    def __init__(self, expected_items: int = 1_000_000, false_positive_rate: float = 0.01):
        # Calculer la taille du bit array
        import math
        self.size = int(-expected_items * math.log(false_positive_rate) / (math.log(2) ** 2))
        self.size = max(self.size, 1024)
        self.num_hashes = int(self.size / expected_items * math.log(2))
        self.num_hashes = max(self.num_hashes, 1)
        self.bit_array = bytearray((self.size + 7) // 8)
        self._count = 0

    def _hashes(self, item: int) -> list:
        """Genere plusieurs positions de hash pour un item."""
        positions = []
        # Utiliser le double hashing
        h1 = item % self.size
        h2 = (item * 0x9E3779B9) % self.size
        for i in range(self.num_hashes):
            pos = (h1 + i * h2) % self.size
            positions.append(pos)
        return positions

    def add(self, item: int):
        """Ajoute un item au Bloom filter."""
        for pos in self._hashes(item):
            self.bit_array[pos // 8] |= (1 << (pos % 8))
        self._count += 1

    def __contains__(self, item: int) -> bool:
        """Teste si un item est probablement dans le Bloom filter."""
        for pos in self._hashes(item):
            if not (self.bit_array[pos // 8] & (1 << (pos % 8))):
                return False
        return True

    @property
    def count(self) -> int:
        return self._count


def filter_unique_sizes(entries: list) -> list:
    """Filtre les fichiers dont la taille est unique (pas de doublon possible).

    Les fichiers de taille 0 sont traites comme un cas special:
    tous les fichiers vides sont considérés comme identiques.
    """
    size_counts = {}
    for e in entries:
        size_counts[e.size] = size_counts.get(e.size, 0) + 1

    # Les fichiers de taille 0 sont toujours consideres comme doublons potentiels
    # (tous les fichiers vides sont identiques)
    result = []
    for e in entries:
        if e.size == 0:
            result.append(e)
        elif size_counts.get(e.size, 0) >= 2:
            result.append(e)
    return result