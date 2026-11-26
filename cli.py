#!/usr/bin/env python
"""CLI de l'agent de scan/comparaison de systeme de fichiers."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# S'assurer que le dossier du script est dans sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ScanConfig, CompareConfig, ensure_dirs
from agent import FilesystemAgent
from reporter import _human


def parse_args():
    p = argparse.ArgumentParser(
        description="Agent de scan et comparaison de fichiers/dossiers multi-disques.")
    p.add_argument("roots", nargs="*", help="Racines a scanner (ex: C:\\ D:\\ E:\\). Si vide, utilise --all-drives.")
    p.add_argument("--all-drives", action="store_true", help="Scanner tous les disques disponibles automatiquement")
    p.add_argument("--output", "-o", default=None, help="Dossier de sortie (defaut: E:/agent_fs/reports)")
    p.add_argument("--cache", default=None, help="Chemin du cache SQLite")
    p.add_argument("--min-size", type=int, default=0, help="Taille minimale (octets)")
    p.add_argument("--max-size", type=int, default=None, help="Taille maximale (octets)")
    p.add_argument("--ext", nargs="*", default=None, help="Filtrer par extensions (ex: .py .txt)")
    p.add_argument("--no-hash", action="store_true", help="Ne pas calculer les hashes")
    p.add_argument("--partial-only", action="store_true", help="Partial hash uniquement (plus rapide)")
    p.add_argument("--workers", type=int, default=8, help="Threads de hashing")
    p.add_argument("--exclude", nargs="*", default=None, help="Dossiers/fichiers a exclure (en plus des defauts)")
    p.add_argument("--follow-symlinks", action="store_true")
    p.add_argument("--skip-symlinks", action="store_true", help="Ignorer les liens symboliques")
    p.add_argument("--min-dup", type=int, default=2, help="Nb min de copies pour etre doublon")
    p.add_argument("--no-unique", action="store_true", help="Ne pas lister les fichiers uniques")
    p.add_argument("--no-by-name", action="store_true", help="Ne pas comparer par nom de fichier")
    p.add_argument("--no-by-size", action="store_true", help="Ne pas grouper par taille")
    p.add_argument("--max-depth", type=int, default=None, help="Profondeur max de scan")
    p.add_argument("--analyze", default=None, help="Analyser un dossier specifique: affiche le plus complet par groupe")
    p.add_argument("--dest", default="E:\\", help="Disque de destination pour reunir les infos (defaut: E:\\)")
    p.add_argument("--incremental", action="store_true", help="Scan incrementiel (ne re-scanner que les dossiers modifies)")
    return p.parse_args()


def analyze_folder(path: str):
    """Analyse un dossier specifique et affiche le plus complet par groupe."""
    from consolidation import create_consolidation_plan, format_consolidation_plan, create_full_consolidation_plan
    import json

    scan_cfg = ScanConfig(roots=[path], compute_hash=True, workers=8)
    agent = FilesystemAgent(scan_cfg, CompareConfig())
    plan = agent.run()

    # Creer le plan de consolidation
    cplans = create_full_consolidation_plan(plan.duplicate_groups, dest_dir=None)
    print(format_consolidation_plan(cplans))

    # Afficher aussi le plus complet par groupe
    print("\n=== PLUS COMPLET PAR GROUPE ===")
    for g in plan.duplicate_groups:
        mc = g.get("most_complete", {})
        print(f"\nGroupe {g['key'][:16]}... ({g['count']} copies):")
        print(f"  MEILLEUR: {mc.get('path', 'N/A')}")
        print(f"    Taille: {mc.get('size', 0)} | Date: {mc.get('mtime', 0)}")
        for f in g["files"]:
            marker = " <-- MEILLEUR" if f.get("is_most_complete") else ""
            print(f"  - {f['path']} (taille: {f.get('size', 0)}, date: {f.get('mtime', 0)}){marker}")
    # Affichage simple
    print(f"\r[{kind}] {n} traites...", end="", flush=True)


def detect_all_drives():
    """Detecte tous les disques disponibles."""
    drives = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\"
            if os.path.exists(path) and os.path.isdir(path):
                drives.append(path)
    else:
        for p in ["/"]:
            if os.path.exists(p) and os.path.isdir(p):
                drives.append(p)
    return drives


def progress(kind, n):
    # Affichage simple
    print(f"\r[{kind}] {n} traites...", end="", flush=True)
    """Detecte tous les disques disponibles."""
    drives = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            path = f"{letter}:\\"
            if os.path.exists(path) and os.path.isdir(path):
                drives.append(path)
    else:
        for p in ["/"]:
            if os.path.exists(p) and os.path.isdir(p):
                drives.append(p)
    return drives


def main():
    args = parse_args()
    ensure_dirs()

    # Mode analyse d'un dossier specifique
    if args.analyze:
        analyze_folder(args.analyze)
        return

    # Determiner les racines a scanner
    if args.all_drives or not args.roots:
        roots = detect_all_drives()
        print(f"Disques detectes: {', '.join(roots)}")
    else:
        roots = args.roots

    if not roots:
        print("Aucun disque/racine a scanner.")
        return

    excludes = None
    if args.exclude:
        from config import DEFAULT_EXCLUDES
        excludes = list(DEFAULT_EXCLUDES) + list(args.exclude)

    scan_cfg = ScanConfig(
        roots=roots,
        excludes=excludes if excludes else None,
        min_size=args.min_size,
        max_size=args.max_size,
        extensions=args.ext,
        max_depth=args.max_depth,
        follow_symlinks=args.follow_symlinks,
        skip_symlinks=args.skip_symlinks,
        incremental=args.incremental,
        compute_hash=not args.no_hash,
        partial_hash_first=True,
        cache_db=args.cache,
        workers=args.workers,
        output_dir=args.output,
    )
    # Si partial-only: on desactive le full hash en mettant compute_hash False
    # mais on garde partial. On gere via un flag custom.
    if args.partial_only:
        scan_cfg.compute_hash = False

    compare_cfg = CompareConfig(
        by_size=not args.no_by_size,
        by_content=not args.no_hash,
        by_name=not args.no_by_name,
        min_duplicate_group=args.min_dup,
        include_unique=not args.no_unique,
    )

    agent = FilesystemAgent(scan_cfg, compare_cfg)

    def on_listing(sr):
        print()  # newline apres progress
        print("\n=== LISTING TERMINE ===")
        print(f"  Fichiers: {sr.total_files}")
        print(f"  Dossiers: {len(sr.dirs)}")
        print(f"  Taille totale: {_human(sr.total_size)}")
        print(f"  Erreurs d'acces: {len(sr.errors)}")
        # Par disque
        by_drive = {}
        for f in sr.files:
            by_drive.setdefault(f.drive, {"files": 0, "size": 0})
            by_drive[f.drive]["files"] += 1
            by_drive[f.drive]["size"] += f.size
        for drv in sorted(by_drive):
            info = by_drive[drv]
            print(f"  Disque {drv}: {info['files']} fichiers, {_human(info['size'])}")
        print(f"  Inventaire sauvegarde: {agent._listing_exports.get('inventory_json')}")
        print("\n--- Comparaison en cours ---")

    print(f"Scan de: {', '.join(roots)}")
    plan = agent.run(progress_cb=progress, on_listing_complete=on_listing)
    print()  # newline apres progress

    print("\n=== RESUME COMPARAISON ===")
    print(f"Fichiers: {plan.summary['total_files']}")
    print(f"Taille totale: {plan.summary['total_size_human']}")
    print(f"Groupes de taille: {plan.summary['num_size_groups']}")
    print(f"Groupes de doublons: {plan.summary['num_duplicate_groups']} "
          f"(cross-disque: {plan.summary['num_cross_drive_dup_groups']})")
    print(f"Fichiers uniques: {plan.summary['num_unique_files']}")
    print(f"Groupes meme nom: {plan.summary.get('num_same_name_groups', 0)}")
    print(f"Dossiers miroirs: {plan.summary['num_mirror_dirs']}")
    print(f"Dossiers vides: {plan.summary.get('num_empty_dirs', 0)}")
    print(f"Liens casses: {plan.summary.get('num_broken_symlinks', 0)}")
    print(f"Dossiers dupliques: {plan.summary.get('num_duplicate_folders', 0)}")
    print(f"Espace recuperable: {plan.summary['recoverable_human']}")
    print("\nExports:")
    for k, v in agent.exports.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
