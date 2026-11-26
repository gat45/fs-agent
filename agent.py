"""Orchestrateur principal de l'agent."""
from __future__ import annotations

import time
import threading
import json
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
from scan_history import ScanHistory


class FilesystemAgent:
    def __init__(self, scan_cfg: ScanConfig, compare_cfg: Optional[CompareConfig] = None):
        ensure_dirs()
        self.scan_cfg = scan_cfg
        self.compare_cfg = compare_cfg or CompareConfig()
        self.scan_result: Optional[ScanResult] = None
        self.plan: Optional[ComparePlan] = None
        self._progress_lock = threading.Lock()
        self.history = ScanHistory()
        self.scan_id: Optional[int] = None
        self.previous_scan_id: Optional[int] = None

    def scan(self, progress_cb: Optional[Callable[[str, int], None]] = None) -> ScanResult:
        self.scan_result = scan_roots(self.scan_cfg.roots, self.scan_cfg, progress_cb)
        return self.scan_result

    def hash(self, progress_cb: Optional[Callable[[str, int], None]] = None) -> None:
        if self.scan_result is None:
            raise RuntimeError("scan() must be called before hash()")
        hash_entries(self.scan_result.files, self.scan_cfg, progress_cb)

    def compare(self) -> ComparePlan:
        if self.scan_result is None:
            raise RuntimeError("scan() must be called before compare()")
        self.plan = compare(self.scan_result.files, self.compare_cfg, self.scan_result,
                            self.history, self.previous_scan_id)
        return self.plan

    def run(self, progress_cb: Optional[Callable[[str, int], None]] = None,
            on_listing_complete: Optional[Callable[[ScanResult], None]] = None,
            progress_file: Optional[str] = None) -> ComparePlan:
        t0 = time.time()
        self._progress_file = progress_file
        self._start_time = t0
        try:
            # Etape 1: LISTING
            self.scan(progress_cb)
            out_dir = self.scan_cfg.resolved_output_dir()
            # Sauvegarder dans l'historique (memoire persistante)
            self.previous_scan_id = None
            try:
                last = self.history.get_last_scan(self.scan_cfg.roots)
                if last:
                    self.previous_scan_id = last["scan_id"]
                self.scan_id = self.history.save_scan(self.scan_result, round(time.time() - t0, 2))
            except Exception:
                pass
            self._listing_exports = {
                "inventory_json": str(write_inventory_json(self.scan_result.to_dict(), out_dir)),
                "inventory_csv": str(write_csv_inventory(
                    [f.to_dict() for f in self.scan_result.files], out_dir)),
            }
            if on_listing_complete:
                on_listing_complete(self.scan_result)
            self._write_progress("scan", len(self.scan_result.files))
            # Etape 2: HASHING
            if self.scan_cfg.compute_hash:
                self.hash(progress_cb)
                self._write_progress("hash", len(self.scan_result.files))
            # Etape 3: COMPARAISON
            self._write_progress("compare", 0)
            self.compare()
            # Etape 4: EXPORTS
            self._write_progress("export", 0)
            plan_path = write_json(self.plan, out_dir)
            dup_path = write_csv_duplicates(self.plan, out_dir)
            uniq_path = write_csv_unique(self.plan, out_dir)
            md_path = write_markdown(self.plan, out_dir)
            from excel_export import export_excel
            xlsx_path = export_excel(self.plan, out_dir)
            self._exports = {
                **self._listing_exports,
                "plan_json": str(plan_path),
                "duplicates_csv": str(dup_path),
                "unique_csv": str(uniq_path),
                "report_md": str(md_path),
                "report_xlsx": str(xlsx_path) if xlsx_path else None,
                "elapsed_sec": round(time.time() - t0, 2),
            }
            self._write_progress("done", 0)
            return self.plan
        except Exception as e:
            self._write_progress("error", 0)
            raise RuntimeError(f"Erreur lors du scan: {e}") from e

    def _write_progress(self, phase: str, n: int):
        if not getattr(self, "_progress_file", None):
            return
        try:
            by_drive = {}
            if self.scan_result:
                for f in self.scan_result.files:
                    by_drive.setdefault(f.drive, {"files": 0, "size": 0})
                    by_drive[f.drive]["files"] += 1
                    by_drive[f.drive]["size"] += f.size
            data = {
                "phase": phase,
                "total_files": len(self.scan_result.files) if self.scan_result else 0,
                "total_dirs": len(self.scan_result.dirs) if self.scan_result else 0,
                "total_size": sum(f.size for f in self.scan_result.files) if self.scan_result else 0,
                "errors": len(self.scan_result.errors) if self.scan_result else 0,
                "by_drive": by_drive,
                "hashed": n if phase == "hash" else 0,
                "last_message": f"Phase: {phase}",
                "elapsed": round(time.time() - self._start_time, 1),
            }
            Path(self._progress_file).write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    @property
    def exports(self) -> dict:
        return getattr(self, "_exports", {})