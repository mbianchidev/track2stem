#!/usr/bin/env python3
import argparse
import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from release import current_version, source_revision, validate_tag

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="Package the independently built VST3/AU targets and CPU runtime")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "plugin/build")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--release-tag")
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        parser.error("Package native Apple Silicon builds on macOS")
    try:
        core = current_version()
        release = validate_tag(args.release_tag) if args.release_tag else {"version": core, "core_version": core, "tag": None}
        revision = source_revision()
    except ValueError as error:
        parser.error(str(error))
    dirty = bool(subprocess.check_output(["git", "-C", ROOT, "status", "--porcelain"], text=True).strip())
    if args.release_tag and dirty:
        parser.error("Release packaging requires a clean source checkout")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "" if args.release_tag else f"-{stamp}"
    output = (args.output or ROOT / "plugin/dist" / f"Track2stem-{release['version']}-macos-arm64{suffix}").resolve()
    archive = Path(f"{output}.zip")
    if output.exists() or archive.exists():
        parser.error("Output already exists; choose a new destination rather than overwriting an artifact")
    build = args.build_dir.resolve()
    runtime = build / "runtime-dist/track2stem-worker"
    if not (runtime / "track2stem-worker").is_file():
        parser.error("Build the complete native runtime first")
    output.parent.mkdir(parents=True, exist_ok=True)
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "VIRTUAL_ENV"}}
    with tempfile.TemporaryDirectory(prefix=".track2stem-package-", dir=output.parent) as temporary:
        package = Path(temporary) / output.name
        package.mkdir()
        for extension in ("vst3", "component"):
            source = build / "out" / f"Track2stem.{extension}"
            subprocess.run(["codesign", "--force", "--sign", "-", source], check=True)
            subprocess.run(["codesign", "--verify", "--strict", source], check=True)
            shutil.copytree(source, package / source.name, symlinks=True)
        shutil.copytree(runtime, package / "Runtime", symlinks=True)
        for name in ("Notices", "ThirdPartySources"):
            shutil.copytree(build / "runtime-dist" / name, package / name)
        for name in ("CMakeLists.txt", "requirements-build.txt", "build.sh", "collect-notices.py", "audit-runtime.py", "release.py"):
            shutil.copy2(ROOT / "plugin" / name, package / "ThirdPartySources" / name)
        shutil.copytree(ROOT / "plugin/patches", package / "ThirdPartySources/patches")
        shutil.copytree(ROOT / "plugin/hooks", package / "ThirdPartySources/hooks", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "plugin/Install.command", package / "Install.command")
        (package / "Install.command").chmod(0o755)
        shutil.copy2(ROOT / "docs/native-plugin.md", package / "Native plugin guide.md")
        shutil.copy2(ROOT / "LICENSE", package / "Notices/Track2stem-LICENSE.txt")
        dependencies = build / "_deps/iplug2-src"
        shutil.copy2(dependencies / "LICENSE.txt", package / "Notices/iPlug2-LICENSE.txt")
        shutil.copy2(dependencies / "IPlug/Extras/WebView/LICENSE.txt", package / "Notices/iPlug2-WebView-LICENSE.txt")
        shutil.copy2(dependencies / "Dependencies/IPlug/VST3_SDK/LICENSE.txt", package / "Notices/VST3-SDK-LICENSE.txt")
        with tempfile.TemporaryDirectory(prefix="track2stem-package-check-") as validation:
            test = subprocess.check_output([
                package / "Runtime/track2stem-worker", "--root", Path(validation) / "data",
                "--models", Path(validation) / "models", "--self-test",
            ], env=environment, text=True)
        report = {**release, "source_revision": revision, "source_dirty": dirty,
                  "architecture": "arm64", "built_at": stamp,
                  "signing": "ad-hoc; not Apple-notarized", "runtime": json.loads(test),
                  "models_bundled": False}
        python_version = report["runtime"]["python_version"]
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE", timeout=30) as response:
            (package / "Notices/CPython-LICENSE.txt").write_bytes(response.read())
        openssl_version = report["runtime"]["openssl_version"].split()[1]
        with urllib.request.urlopen(f"https://raw.githubusercontent.com/openssl/openssl/openssl-{openssl_version}/LICENSE.txt", timeout=30) as response:
            (package / "Notices/OpenSSL-LICENSE.txt").write_bytes(response.read())
        report["runtime_audit"] = json.loads((build / "runtime-dist/RuntimeAudit.json").read_text())
        (package / "BuildInfo.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        package.rename(output)
    partial = archive.with_suffix(".zip.part")
    try:
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", output, partial], check=True)
        partial.rename(archive)
    finally:
        partial.unlink(missing_ok=True)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(archive)


if __name__ == "__main__":
    main()
