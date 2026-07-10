"""Find any reference to D:\分镜图 or similar hardcoded output paths"""
import re
from pathlib import Path

project = Path(__file__).parent
search_terms = ["分镜图", "storyboard"]

for py in project.rglob("*.py"):
    text = py.read_text(encoding="utf-8", errors="ignore")
    for term in search_terms:
        if term in text:
            for i, line in enumerate(text.split("\n"), 1):
                if term in line:
                    print(f"{py.relative_to(project)}:{i}: {line.strip()}")

# Also find any absolute D:\ paths in .py files (that aren't the project dir itself)
for py in sorted(project.rglob("*.py")):
    text = py.read_text(encoding="utf-8", errors="ignore")
    for i, line in enumerate(text.split("\n"), 1):
        # Look for D:\ paths in string literals
        for m in re.finditer(r"""['"]((?:D|d):\\[^'"\\ ]+(?:\\[^'"\\ ]+)+)['"]""", line):
            p = m.group(1)
            if "讲书升级Agent" not in p and "output" not in p.lower() and "\\0\\" not in p:
                print(f"{py.relative_to(project)}:{i}: {p}")
