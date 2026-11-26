d = open("E:/agent_fs/cli.py").read()
for i, l in enumerate(d.splitlines()):
    if 'f"' in l and '{' not in l:
        print(i+1, l)
