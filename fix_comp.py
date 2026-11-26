d = open("E:/agent_fs/comparator.py").read()
# Supprimer le bloc except a la fin de compare()
old = """    return plan
except Exception as e:
    # En cas d'erreur, retourner le plan tel quel
    try:
        plan.summary = {"error": str(e), "total_files": len(files), "total_size": sum(f.size for f in files)}
    except Exception:
        pass
    return plan


def _human(n: int) -> str:"""
new = """    return plan


def _human(n: int) -> str:"""
assert old in d, "old not found"
d = d.replace(old, new)
open("E:/agent_fs/comparator.py", "w").write(d)
print("Done")
