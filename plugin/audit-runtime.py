import argparse
import json
from pathlib import Path

from macholib.MachO import MachO
from macholib.mach_o import LC_BUILD_VERSION, LC_ID_DYLIB, LC_RPATH, LC_VERSION_MIN_MACOSX, dylib_command

parser = argparse.ArgumentParser(description="Check native runtime linkage and deployment requirements")
parser.add_argument("runtime", type=Path)
parser.add_argument("--prune-unused-libraries", action="store_true")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
root = args.runtime.resolve()
resources = root / "_internal"
magic_values = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}


def inspect():
    references, external = set(), []
    minimum = (0, "")
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        with path.open("rb") as source:
            if source.read(4) not in magic_values:
                continue
        for header in MachO(str(path)).headers:
            for load, command, data in header.commands:
                if (isinstance(command, dylib_command) and load.cmd != LC_ID_DYLIB) or load.cmd == LC_RPATH:
                    value = data.split(b"\0")[0].decode()
                    if load.cmd != LC_RPATH:
                        references.add(Path(value).name)
                        alias = resources / Path(value).name
                        if alias.exists():
                            references.add(alias.resolve().name)
                    if value.startswith("/") and not value.startswith(("/usr/lib/", "/System/Library/")):
                        external.append({"binary": str(path.relative_to(root)), "reference": value})
                if load.cmd in (LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX):
                    version = command.minos if load.cmd == LC_BUILD_VERSION else command.version
                    if version > minimum[0]:
                        minimum = version, str(path.relative_to(root))
    return references, external, minimum


removed = []
if args.prune_unused_libraries:
    while True:
        references, _, _ = inspect()
        unused = [path for path in resources.glob("*.dylib") if not path.is_symlink()
                  and path.name.startswith(("libSvtAv1Enc.", "libdav1d.", "libaom.", "libx264.", "libx265.", "libvpx.", "libheif.", "libvmaf.",
                                            "libmp3lame.", "libmpg123.", "libopus.", "libogg.", "libvorbis.",
                                            "libvorbisenc.", "libvorbisfile.", "libFLAC.", "libssl.", "libcrypto.", "liblzma."))
                  and path.name not in references]
        if not unused:
            break
        for path in unused:
            removed.append(path.name)
            path.unlink()
_, external, minimum = inspect()
if external:
    raise RuntimeError(f"Runtime still references machine-local libraries: {external}")
version = minimum[0]
report = {
    "external_library_references": external,
    "minimum_macos": f"{version >> 16}.{(version >> 8) & 255}",
    "limiting_binary": minimum[1],
    "removed_unreferenced_libraries": removed,
}
if args.output:
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
