content = open("E:/agent_fs/comparator.py").read()
# Find the end of compare function (before _human)
idx = content.find("def _human(n: int)")
# Find the last "return plan" before _human
last_return = content.rfind("    return plan", 0, idx)
# Replace from last_return to idx
old_tail = content[last_return:idx]
new_tail = """    return plan
except Exception as e:
    # En cas d'erreur, retourner le plan tel quel
    try:
        plan.summary = {"error": str(e), "total_files": len(files), "total_size": sum(f.size for f in files)}
    except Exception:
        pass
    return plan


"""
content = content[:last_return] + new_tail + content[idx:]
open("E:/agent_fs/comparator.py", "w").write(content)
print("Done")
import ast
ast.parse(open("E:/agent_fs/comparator.py").read())
print("Syntax OK")
