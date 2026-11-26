#!/usr/bin/env python
"""CLI de l'agent de scan et comparaison de systeme de fichiers."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# S'assurer que le dossier du script est dans sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import ScanConfig, CompareConfig, ensure_dirs, REPORTS_DIR
from agent import FilesystemAgent
from reporter import _human


def parse_args():
    p = argparse.ArgumentParser(
        description="Agent de scan et comparaison de fichiers/dossiers multi-disques.")
    p.add_argument("roots", nargs="*", help="Racines a scanner (ex: C:\\ D:\\ E:\\). Si vide, utilise --all-drives.")
    p.add_argument("--all-drives", action="store_true", help="Scanner tous les disques disponibles automatiquement")
    p.add_argument("--output", "-o", default=None, help=f"Dossier de sortie (defaut: {REPORTS_DIR})")
    p.add_argument("--cache", default=None, help="Chemin du cache SQLite")
    p.add_argument("--min-size", type=int, default=0, help="Taille minimale (octets)")
    p.add_argument("--max-size", type=int, default=None, help="Taille maximale (octets)")
    p.add_argument("--ext", nargs="*", default=None, help="Filtrer par extensions (ex: .py .txt)")
    p.add_argument("--no-hash", action="store_true", help="Ne pas calculer les hashes")
    p.add_argument("--partial-only", action="store_true", help="Partial hash uniquement (plus rapide)")
    p.add_argument("--workers", type=int, default=8, help="Threads de hashing")
    p.add_argument("--io-threads", type=int, default=2, help="Threads I/O par disque (2 pour HDD, 8+ pour SSD)")
    p.add_argument("--io-throttle", type=int, default=0, help="Delai en ms entre les lectures (0 = pas de throttle)")
    p.add_argument("--sequential", action="store_true", help="Mode sequentiel (1 thread, ideal pour HDD)")
    p.add_argument("--exclude", nargs="*", default=None, help="Dossiers/fichiers a exclure (en plus des defauts)")
    p.add_argument("--follow-symlinks", action="store_true")
    p.add_argument("--skip-symlinks", action="store_true", help="Ignorer les liens symboliques")
    p.add_argument("--min-dup", type=int, default=2, help="Nb min de copies pour etre doublon")
    p.add_argument("--no-unique", action="store_true", help="Ne pas lister les fichiers uniques")
    p.add_argument("--no-by-name", action="store_true", help="Ne pas comparer par nom de fichier")
    p.add_argument("--no-by-size", action="store_true", help="Ne pas grouper par taille")
    p.add_argument("--max-depth", type=int, default=None, help="Profondeur max de scan")
    p.add_argument("--analyze", default=None, help="Analyser un dossier specifique")
    p.add_argument("--llm-analyze", action="store_true", help="Analyser avec OpenCode (LLM)")
    p.add_argument("--dest", default=None, help="Disque/dossier de destination (optionnel)")
    p.add_argument("--incremental", action="store_true", help="Scan incrementiel")
    p.add_argument("--dashboard", action="store_true", help="Lancer le dashboard HTML en temps reel")
    p.add_argument("--progress-file", default=None, help="Fichier progress.json")
    p.add_argument("--schedule", default=None, help="Planifier un scan automatique (daily/weekly)")
    p.add_argument("--cloud", default=None, help="Scanner un bucket cloud (s3://bucket, azure://container, gs://bucket)")
    p.add_argument("--compare-md", action="store_true", help="Comparer les rapports Markdown et fichiers texte similaires")
    p.add_argument("--config", default=None, help="Fichier de configuration JSON")
    p.add_argument("--interactive", action="store_true", help="Mode interactif (choisir fichier par fichier)")
    return p.parse_args()


def interactive_mode(plan, agent):
    """Mode interactif: l'utilisateur choisit quoi faire pour chaque groupe."""
    print("\n" + "=" * 60)
    print("MODE INTERACTIF - Aucune action sans votre confirmation")
    print("=" * 60)

    for i, g in enumerate(plan.duplicate_groups, 1):
        print(f"\n--- Groupe {i}/{len(plan.duplicate_groups)} ---")
        print(f"  Hash: {g['key'][:16]}... | Taille: {_human(g['size'])} | Copies: {g['count']}")
        mc = g.get("most_complete", {})
        print(f"  Meilleur: {mc.get('path', 'N/A')}")
        for f in g["files"]:
            marker = " <-- MEILLEUR" if f.get("is_most_complete") else ""
            print(f"    {f['path']}{marker}")

        print("\n  Options:")
        print("    [k] Garder le meilleur, archiver les autres")
        print("    [c] Copier vers un dossier de destination")
        print("    [i] Ignorer ce groupe")
        print("    [q] Quitter")

        choice = input("  Votre choix (k/c/i/q): ").strip().lower()
        if choice == "q":
            print("Arret du mode interactif.")
            break
        elif choice == "i":
            print("  Groupe ignore.")
            continue
        elif choice == "k":
            print(f"  Reference: {mc.get('path', 'N/A')}")
            print(f"  Les {g['count']-1} autres copies sont conservees (aucune suppression).")
        elif choice == "c":
            dest = input("  Dossier de destination: ").strip()
            if dest:
                print(f"  Copie vers {dest} (a executer manuellement)")
        else:
            print("  Choix invalide, groupe ignore.")

    print("\n" + "=" * 60)
    print("Mode interactif termine. Aucune action n'a ete executee.")
    print("=" * 60)


def progress(kind, n):
    print(f"\r[{kind}] {n} traites...", end="", flush=True)
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


def analyze_folder(path: str):
    from consolidation import create_full_consolidation_plan, format_consolidation_plan
    scan_cfg = ScanConfig(roots=[path], compute_hash=True, workers=8)
    agent = FilesystemAgent(scan_cfg, CompareConfig())
    plan = agent.run()
    cplans = create_full_consolidation_plan(plan.duplicate_groups, dest_dir=None)
    print(format_consolidation_plan(cplans))
    print("\n=== PLUS COMPLET PAR GROUPE ===")
    for g in plan.duplicate_groups:
        mc = g.get("most_complete", {})
        print(f"\nGroupe {g['key'][:16]}... ({g['count']} copies):")
        print(f"  MEILLEUR: {mc.get('path', 'N/A')}")
        for f in g["files"]:
            marker = " <-- MEILLEUR" if f.get("is_most_complete") else ""
            print(f"  - {f['path']} (taille: {f.get('size', 0)}, date: {f.get('mtime', 0)}){marker}")


def main():
    args = parse_args()
    ensure_dirs()

    # Charger la configuration depuis un fichier si specifie
    from config_file import load_config
    file_cfg = load_config(Path(args.config) if args.config else None)

    # Appliquer les valeurs du fichier de config (sauf si l'utilisateur a specifie explicitement)
    if args.config:
        if not args.roots and file_cfg.get("roots"):
            args.roots = file_cfg["roots"]
        if not args.all_drives and file_cfg.get("all_drives"):
            args.all_drives = file_cfg["all_drives"]
        if args.min_size == 0 and file_cfg.get("min_size", 0) > 0:
            args.min_size = file_cfg["min_size"]
        if args.max_size is None and file_cfg.get("max_size"):
            args.max_size = file_cfg["max_size"]
        if args.workers == 8 and file_cfg.get("workers", 8) != 8:
            args.workers = file_cfg["workers"]

    # Mode dashboard
    if args.dashboard or file_cfg.get("dashboard"):
        import subprocess
        subprocess.Popen([sys.executable, "serve_dashboard.py"], cwd=str(Path(__file__).resolve().parent))
        print("Dashboard lance sur http://localhost:8766/dashboard.html")

    # Fichier de progression
    if args.progress_file:
        progress_file = args.progress_file
    elif args.dashboard:
        progress_file = str(Path(args.output or REPORTS_DIR) / "progress.json")
    else:
        progress_file = None

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

    # Limiter a 6 racines max
    if len(roots) > 6:
        print(f"Attention: maximum 6 disques/dossiers par scan. Seuls les 6 premiers seront scannes.")
        roots = roots[:6]

    excludes = None
    if args.exclude:
        from config import DEFAULT_EXCLUDES
        excludes = list(DEFAULT_EXCLUDES) + list(args.exclude)

    # Auto-detection du type de disque
    if not args.sequential and args.io_threads == 2:
        try:
            from disk_type import optimal_io_threads_multi
            optimal = optimal_io_threads_multi(roots)
            if optimal != args.io_threads:
                print(f"Type de disque detecte: {optimal} threads I/O recommandes")
                args.io_threads = optimal
        except Exception:
            pass

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
        io_threads=1 if args.sequential else args.io_threads,
        io_throttle_ms=args.io_throttle,
        output_dir=args.output,
    )
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
        print()
        print("\n=== LISTING TERMINE ===")
        print(f"  Fichiers: {sr.total_files}")
        print(f"  Dossiers: {len(sr.dirs)}")
        print(f"  Taille totale: {_human(sr.total_size)}")
        print(f"  Erreurs d'acces: {len(sr.errors)}")
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
    plan = agent.run(progress_cb=progress, on_listing_complete=on_listing, progress_file=progress_file)
    print()

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
    # Mode LLM analysis
    if args.llm_analyze:
        from llm_analysis import generate_analysis_report
        report_path = os.path.join(args.output or REPORTS_DIR, "llm_analysis.md")
        generate_analysis_report(plan.duplicate_groups, report_path, use_opencode=True)
        print(f"\nRapport LLM sauvegarde: {report_path}")
    # Mode interactif
    if args.interactive:
        interactive_mode(plan, agent)
    print("\nExports:")
    for k, v in agent.exports.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
