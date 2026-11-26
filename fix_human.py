content = open("E:/agent_fs/comparator.py", "rb").read()
content = content.replace(b"\x00", b"")
human_func = '''
def _human(n: int) -> str:
    for unit in ("B", "Ko", "Mo", "Go", "To"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} Po"
'''
content += human_func.encode()
open("E:/agent_fs/comparator.py", "wb").write(content)
print("Done")
