import argparse
import importlib.metadata
import re
import shutil
from pathlib import Path

parser = argparse.ArgumentParser(description="Retain installed dependency licenses for native distribution")
parser.add_argument("output", type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
for distribution in importlib.metadata.distributions():
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", distribution.metadata["Name"])
    destination = args.output / name
    destination.mkdir(exist_ok=True)
    metadata = distribution.read_text("METADATA")
    if metadata:
        (destination / "METADATA.txt").write_text(metadata, encoding="utf-8")
    for relative in distribution.files or []:
        path = Path(distribution.locate_file(relative))
        license_directory = any(part.lower() in {"license", "licenses"} for part in Path(relative).parts[:-1])
        if not path.is_file() or not (license_directory or path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "COPYRIGHT", "AUTHORS"))):
            continue
        filename = re.sub(r"[^a-zA-Z0-9._-]", "_", str(relative))
        shutil.copy2(path, destination / filename)
