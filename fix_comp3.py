content = open("E:/agent_fs/comparator.py").read()
# Remove the try: at the beginning of compare
content = content.replace(
    "def compare(files, cfg: CompareConfig, scan_result=None, history=None, previous_scan_id=None) -> ComparePlan:\n    try:\n        plan = ComparePlan(",
    "def compare(files, cfg: CompareConfig, scan_result=None, history=None, previous_scan_id=None) -> ComparePlan:\n    plan = ComparePlan("
)
# Remove the except block at the end
import re
content = content.replace(
    """    return plan
except Exception as e:
    # En cas d'erreur, retourner le plan tel quel
    try:
        plan.summary = {"error": str(e), "total_files": len(files), "total_size": sum(f.size for f in files)}
    except Exception:
        pass
    return plan


def _human""",
    """    return plan


def _human"""
)
open("E:/agent_fs/comparator.py", "w").write(content)
print("Done")
import ast
ast.parse(open("E:/agent_fs/comparator.py").read())
print("Syntax OK")
