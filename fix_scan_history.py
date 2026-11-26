d = open("E:/agent_fs/scan_history.py").read()
# Check if hash comparison is already present
if 'old.get("full_hash")' in d:
    print("Already updated")
else:
    # Find the compare_scans method and update it
    old = '''        for path, f in new_files.items():
            if path not in old_files:
                added.append(f)
            else:
                old = old_files[path]
                if old["size"] != f["size"] or old["mtime"] != f["mtime"]:
                    modified.append({"old": old, "new": f})
                else:
                    unchanged.append(f)'''
    new = '''        for path, f in new_files.items():
            if path not in old_files:
                added.append(f)
            else:
                old = old_files[path]
                changed = False
                if old["size"] != f["size"] or old["mtime"] != f["mtime"]:
                    changed = True
                elif old.get("full_hash") and f.get("full_hash") and old["full_hash"] != f["full_hash"]:
                    changed = True
                elif old.get("partial_hash") and f.get("partial_hash") and old["partial_hash"] != f["partial_hash"]:
                    changed = True
                if changed:
                    modified.append({"old": old, "new": f})
                else:
                    unchanged.append(f)'''
    assert old in d, "old not found"
    d = d.replace(old, new)
    open("E:/agent_fs/scan_history.py", "w").write(d)
    print("Updated")
import ast
ast.parse(open("E:/agent_fs/scan_history.py").read())
print("Syntax OK")
