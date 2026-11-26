"""Orchestrateur principal de l'agent."""
from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Callable, List, Optional

from config import ScanConfig, CompareConfig, ensure_dirs
from scanner import scan_roots, ScanResult
from hasher import hash_entries
from comparator import compare, ComparePlan
from reporter import (
    write_json, write_inventory_json, write_csv_duplicates,
    write_csv_unique, write_csv_inventory, write_markdown,
)


class FilesystemAgent:
    def __init__(self, scan_cfg: ScanConfig, compare_cfg: Optional[CompareConfig] = None):
        ensure_dirs()
        self.scan_cfg = scan_cfg
        self.compare_cfg = compare_cfg or CompareConfig()
        self.scan_result: Optional[ScanResult] = None
        self.plan: Optional[ComparePlan] = None
        self._progress_lock = threading.Lock()

    def scan(self, progress_cb: Optional[Callable[[str, int], None]] = None) -> ScanResult:
        def _cb(n):
            if progress_cb:
                with self._progress_lock:
                    progress_cb("scan", n)
        self.scan_result = scan_roots(self.scan_cfg.roots, self.scan_cfg, _cb)
        return self.scan_result

    def hash(self, progress_cb: Optional[Callable[[str, int], None]] = None) -> None:
        if self.scan_result is None:
            raise RuntimeError("scan() must be called before hash()")
        def _cb(n):
            if progress_cb:
                with self._progress_lock:
                    progress_cb("hash", n)
        hash_entries(self.scan_result.files, self.scan_cfg, _cb)

    def compare(self) -> ComparePlan:
        if self.scan_result is None:
            raise RuntimeError("scan() must be called before compare()")
        self.plan = compare(self.scan_result.files, self.compare_cfg, self.scan_result)
        return self.plan

    def run(self, progress_cb: Optional[Callable[[str, int], None]] = None,
            on_listing_complete: Optional[Callable[[ScanResult], None]] = None) -> ComparePlan:
        t0 = time.time()
        # Etape 1: LISTING - lister tous les fichiers et dossiers de chaque disque
        self.scan(progress_cb)
        out_dir = self.scan_cfg.resolved_output_dir()
        self._listing_exports = {
            "inventory_json": str(write_inventory_json(self.scan_result.to_dict(), out_dir)),
            "inventory_csv": str(write_csv_inventory(
                [f.to_dict() for f in self.scan_result.files], out_dir)),
        }
        if on_listing_complete:
            on_listing_complete(self.scan_result)
        # Etape 2: HASHING (si demande)
        if self.scan_cfg.compute_hash:
            self.hash(progress_cb)
        # Etape 3: COMPARAISON
        self.compare()
        # Passer scan_result a compare (deja fait via self.scan_result)
        # Etape 4: EXPORTS du plan (aucune suppression automatique)
        plan_path = write_json(self.plan, out_dir)
        dup_path = write_csv_duplicates(self.plan, out_dir)
        uniq_path = write_csv_unique(self.plan, out_dir)
        md_path = write_markdown(self.plan, out_dir)
        self._exports = {
            **self._listing_exports,
            "plan_json": str(plan_path),
            "duplicates_csv": str(dup_path),
            "unique_csv": str(uniq_path),
            "report_md": str(md_path),
            "elapsed_sec": round(time.time() - t0, 2),
        }
        return self.plan

    @property
    def exports(self) -> dict:
        return getattr(self, "_exports", {})
