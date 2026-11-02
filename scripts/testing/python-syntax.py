"""Compile tracked Python sources in memory without importing or writing pyc files."""
import subprocess
from pathlib import Path

paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "*.py"]).decode().split("\0")
for name in sorted(set(filter(None, paths))):
    path = Path(name)
    if path.is_file():
        compile(path.read_bytes(), name, "exec")
print("Python syntax checked")
