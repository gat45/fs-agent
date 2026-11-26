d = open("E:/agent_fs/comparator.py").read()
lines = d.splitlines()
seen = False
new_lines = []
for line in lines:
    if '"files_added"' in line:
        if seen:
            continue
        seen = True
    new_lines.append(line)
open("E:/agent_fs/comparator.py", "w").write("\n".join(new_lines))
print("Done")
import ast
ast.parse(open("E:/agent_fs/comparator.py").read())
print("Syntax OK")
