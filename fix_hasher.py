d = open("E:/agent_fs/hasher.py").read()
# Remove redundant "import time" lines
lines = d.splitlines()
new_lines = []
for line in lines:
    if line.strip() == "import time":
        continue
    new_lines.append(line)
# Add time.sleep import where needed (already imported via time.sleep)
# But we removed the import, so we need to add it back at the top
# Actually, time is not used at module level anymore, only in hash_file and hash_entries
# Add "import time" to the top imports
for i, line in enumerate(new_lines):
    if line.startswith("from pathlib import Path"):
        new_lines.insert(i+1, "import time")
        break
open("E:/agent_fs/hasher.py", "w").write("\n".join(new_lines))
print("Done")
# Verify
import ast
ast.parse(open("E:/agent_fs/hasher.py").read())
print("Syntax OK")
