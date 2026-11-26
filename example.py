"""Exemple d'utilisation programmatique de l'agent."""
import sys
sys.path.insert(0, "E:/agent_fs")

from config import ScanConfig, CompareConfig
from agent import FilesystemAgent

# 1. Configuration du scan
scan_cfg = ScanConfig(
    roots=["E:/agent_fs", "E:/temp/opencode"],
    min_size=0,
    compute_hash=True,
    workers=8,
    output_dir="E:/agent_fs/reports_example",
)

# 2. Configuration de la comparaison
compare_cfg = CompareConfig(
    by_size=True,
    by_content=True,
    by_name=True,
    include_unique=True,
    min_duplicate_group=2,
)

# 3. Execution
agent = FilesystemAgent(scan_cfg, compare_cfg)
plan = agent.run()

# 4. Exploitation du plan
print("Fichiers:", plan.summary["total_files"])
print("Doublons:", plan.summary["num_duplicate_groups"])
print("Recuperable:", plan.summary["recoverable_human"])

# Acces aux doublons
for g in plan.duplicate_groups[:5]:
    print(f"  Doublon {g['key'][:12]}: {g['count']} copies, {g['wasted_bytes']} octets gaspilles")
    for f in g["files"]:
        print(f"    - {f['path']}")

# Acces aux exports
print("\nExports:")
for k, v in agent.exports.items():
    print(f"  {k}: {v}")
