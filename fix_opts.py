d = open("E:/agent_fs/cli.py").read()
lines = d.splitlines()
# Check if --max-depth exists
has_max_depth = any("--max-depth" in l for l in lines)
print("has_max_depth:", has_max_depth)
# Add if missing
if not has_max_depth:
    # Find the line with --no-by-size
    for i, l in enumerate(lines):
        if "--no-by-size" in l:
            lines.insert(i+1, '    p.add_argument("--max-depth", type=int, default=None, help="Profondeur max de scan")')
            break
    open("E:/agent_fs/cli.py", "w").write("\n".join(lines))
    print("Added --max-depth")
else:
    print("Already present")
