content = open("E:/agent_fs/comparator.py", "rb").read()
# Find the last occurrence of "return plan" and add a newline + _human after it
idx = content.rfind(b"return plan")
if idx != -1:
    content = content[:idx + len(b"return plan")] + b"\n\n" + content[idx + len(b"return plan"):]
# Remove any duplicate _human definitions
import re
# Find all _human definitions and keep only the last one
parts = content.split(b"def _human(n: int) -> str:")
if len(parts) > 2:
    # Keep everything up to the first _human, then add one _human at the end
    content = parts[0] + b"def _human(n: int) -> str:" + parts[-1]
open("E:/agent_fs/comparator.py", "wb").write(content)
print("Done")
# Verify
import ast
ast.parse(open("E:/agent_fs/comparator.py").read())
print("Syntax OK")
