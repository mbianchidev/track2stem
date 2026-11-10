#!/usr/bin/env python3
import argparse
import hashlib
import json
import plistlib
import re
import struct
import subprocess
import zipfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent
ROOT = PLUGIN.parent
NUMBER = r"(?:0|[1-9][0-9]*)"
CORE = rf"{NUMBER}\.{NUMBER}\.{NUMBER}"
SEMVER = re.compile(rf"({CORE})(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")


def current_version(plugin=PLUGIN):
    header = (plugin / "config.h").read_text(encoding="utf-8")
    text = re.search(r'^\s*#define\s+PLUG_VERSION_STR\s+"([^"]+)"', header, re.MULTILINE)
    hexadecimal = re.search(r"^\s*#define\s+PLUG_VERSION_HEX\s+(0x[0-9a-fA-F]+)\b", header, re.MULTILINE)
    cmake = re.search(r"^\s*project\s*\(\s*Track2stem\s+VERSION\s+([0-9.]+)\b",
                      (plugin / "CMakeLists.txt").read_text(encoding="utf-8"), re.MULTILINE)
    if not text or not hexadecimal or not cmake or not re.fullmatch(CORE, text[1]):
        raise ValueError("Native version must be declared in config.h and CMakeLists.txt as X.Y.Z")
    version = text[1]
    major, minor, patch = map(int, version.split("."))
    if major > 65535 or minor > 255 or patch > 255:
        raise ValueError("Version exceeds the native iPlug version field range")
    if int(hexadecimal[1], 16) != (major << 16 | minor << 8 | patch):
        raise ValueError("Native hexadecimal plugin version does not match PLUG_VERSION_STR")
    if cmake[1] != version:
        raise ValueError("CMake project version does not match the plugin version")
    return version


def validate_tag(tag, plugin=PLUGIN):
    match = SEMVER.fullmatch(tag[1:]) if isinstance(tag, str) and tag.startswith("v") else None
    if not match:
        raise ValueError("Use a canonical vX.Y.Z SemVer tag, optionally with prerelease/build metadata")
    core, prerelease, _ = match.groups()
    if prerelease and any(part.isdecimal() and len(part) > 1 and part.startswith("0") for part in prerelease.split(".")):
        raise ValueError("Numeric prerelease identifiers cannot have leading zeroes")
    if current_version(plugin) != core:
        raise ValueError("Release tag version does not match the committed native plugin version")
    return {"version": tag[1:], "core_version": core, "tag": tag, "prerelease": prerelease is not None}


def source_revision(root=ROOT):
    try:
        revision = subprocess.check_output(["git", "-C", root, "rev-parse", "--verify", "HEAD"],
                                           text=True, stderr=subprocess.PIPE).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError(f"Cannot determine the release source revision: {error.stderr.strip()}") from error
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", revision):
        raise ValueError("Git returned an unsupported source revision")
    return revision


def check_tag_revision(tag, revision, root=ROOT):
    try:
        actual = subprocess.check_output(
            ["git", "-C", root, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
            text=True, stderr=subprocess.PIPE,
        ).strip()
    except subprocess.CalledProcessError as error:
        raise ValueError("The exact release tag is missing from this checkout") from error
    if actual != revision:
        raise ValueError("The release tag no longer identifies the checked-out source revision")


def check_remote_tag(tag, revision, root=ROOT):
    reference = f"refs/tags/{tag}"
    try:
        output = subprocess.check_output(
            ["git", "-C", root, "ls-remote", "--tags", "origin", reference, reference + "^{}"],
            text=True, stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        raise ValueError(f"Cannot verify the remote release tag: {error.stderr.strip()}") from error
    refs = {}
    for line in output.splitlines():
        sha, name = line.split()
        refs[name] = sha
    actual = refs.get(reference + "^{}", refs.get(reference))
    if actual != revision:
        raise ValueError("The remote release tag is missing or changed since the verified build")


def verify_assets(directory, release, revision):
    name = f"Track2stem-{release['version']}-macos-arm64"
    archive = directory / f"{name}.zip"
    checksum = archive.with_suffix(".zip.sha256")
    if sorted(directory.glob("Track2stem-*.zip")) != [archive]:
        raise ValueError("Expected exactly the versioned macOS arm64 release ZIP")
    try:
        expected, filename = checksum.read_text(encoding="ascii").strip().split(maxsplit=1)
    except (OSError, ValueError) as error:
        raise ValueError("The release checksum sidecar is missing or malformed") from error
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if expected != actual or filename != archive.name:
        raise ValueError("Release ZIP checksum or sidecar filename does not match")
    with zipfile.ZipFile(archive) as package:
        def read(relative):
            try:
                entry = package.getinfo(f"{name}/{relative}")
            except KeyError as error:
                raise ValueError(f"Release ZIP is missing {relative}") from error
            if not 0 < entry.file_size <= 1024 * 1024:
                raise ValueError(f"Release metadata has an invalid size: {relative}")
            return package.read(entry)

        report = json.loads(read("BuildInfo.json"))
        for field in ("version", "core_version", "tag"):
            if report.get(field) != release[field]:
                raise ValueError(f"Release package {field} does not match the selected tag")
        if report.get("source_revision") != revision or report.get("source_dirty") is not False:
            raise ValueError("Release package source revision does not match the selected tag")
        if (report.get("architecture") != "arm64" or report.get("models_bundled") is not False
                or report.get("runtime", {}).get("cpu_only") is not True
                or report.get("runtime_audit", {}).get("external_library_references") != []):
            raise ValueError("Release package does not satisfy the portable arm64 CPU runtime contract")

        def arm64(relative):
            try:
                with package.open(f"{name}/{relative}") as source:
                    header = source.read(8)
            except KeyError as error:
                raise ValueError(f"Release ZIP is missing {relative}") from error
            if len(header) != 8 or struct.unpack("<II", header) != (0xFEEDFACF, 0x0100000C):
                raise ValueError(f"Release executable is not a native arm64 Mach-O: {relative}")

        arm64("Runtime/track2stem-worker")
        read("Install.command")
        for extension, identifier in (("vst3", "vst3"), ("component", "audiounit")):
            bundle = f"Track2stem.{extension}/Contents"
            metadata = plistlib.loads(read(f"{bundle}/Info.plist"))
            if (metadata.get("CFBundleIdentifier") != f"dev.track2stem.{identifier}.Track2stem"
                    or metadata.get("CFBundleVersion") != release["core_version"]
                    or metadata.get("CFBundleShortVersionString") != release["core_version"]):
                raise ValueError("Release bundle identity/version does not match its tag core")
            arm64(f"{bundle}/MacOS/Track2stem")
    return {"version": release["version"], "source_revision": revision,
            "assets": [str(archive), str(checksum)], "sha256": actual}


def main():
    parser = argparse.ArgumentParser(description="Validate native release tags and verified publication assets")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate-tag")
    action.add_argument("--verify-assets", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--source-sha")
    parser.add_argument("--check-ref", action="store_true")
    parser.add_argument("--check-remote", action="store_true")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        release = validate_tag(args.validate_tag or args.tag)
        if args.validate_tag:
            revision = source_revision()
            if args.check_ref:
                check_tag_revision(release["tag"], revision)
            if args.check_remote:
                check_remote_tag(release["tag"], revision)
            result = {**release, "source_sha": revision}
            if args.github_output:
                with args.github_output.open("a", encoding="utf-8") as target:
                    for key, value in result.items():
                        target.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
        else:
            if not args.source_sha:
                parser.error("--source-sha is required when verifying downloaded assets")
            result = verify_assets(args.verify_assets, release, args.source_sha)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.error(str(error))
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
