import hashlib
import json
import os
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release import check_remote_tag, check_tag_revision, current_version, source_revision, validate_tag, verify_assets


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.plugin = self.root / "plugin"
        self.plugin.mkdir()
        (self.plugin / "config.h").write_text(
            '#define PLUG_VERSION_STR "1.2.3"\n#define PLUG_VERSION_HEX 0x00010203\n')
        (self.plugin / "CMakeLists.txt").write_text("project(Track2stem VERSION 1.2.3 LANGUAGES CXX)\n")
        self.sha = "a" * 40

    def package(self, tag="v1.2.3", *, manifest_version=None, architecture=0x0100000C, dirty=False):
        version = tag[1:]
        name = f"Track2stem-{version}-macos-arm64"
        archive = self.root / f"{name}.zip"
        header = struct.pack("<II", 0xFEEDFACF, architecture) + b"synthetic Mach-O fixture"
        metadata = {
            "version": manifest_version or version, "core_version": "1.2.3", "tag": tag,
            "source_revision": self.sha, "source_dirty": dirty, "architecture": "arm64", "models_bundled": False,
            "runtime": {"cpu_only": True}, "runtime_audit": {"external_library_references": []},
        }
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr(f"{name}/BuildInfo.json", json.dumps(metadata))
            target.writestr(f"{name}/Runtime/track2stem-worker", header)
            target.writestr(f"{name}/Install.command", "#!/bin/bash\nexit 0\n")
            for extension, identifier in (("vst3", "vst3"), ("component", "audiounit")):
                bundle = f"{name}/Track2stem.{extension}/Contents"
                target.writestr(f"{bundle}/MacOS/Track2stem", header)
                target.writestr(f"{bundle}/Info.plist", plistlib.dumps({
                    "CFBundleIdentifier": f"dev.track2stem.{identifier}.Track2stem",
                    "CFBundleShortVersionString": "1.2.3", "CFBundleVersion": "1.2.3",
                }))
        self.checksum(archive)
        return archive

    @staticmethod
    def checksum(archive):
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")

    def test_tag_identity_preserves_prerelease_and_build_metadata(self):
        release = validate_tag("v1.2.3-rc.2+build.007", self.plugin)
        self.assertEqual(release["version"], "1.2.3-rc.2+build.007")
        self.assertEqual(release["core_version"], "1.2.3")
        self.assertTrue(release["prerelease"])
        self.package(release["tag"])
        result = verify_assets(self.root, release, self.sha)
        self.assertEqual(result["version"], release["version"])
        self.assertEqual(len(result["assets"]), 2)

    def test_invalid_or_mismatched_tags_cannot_release_another_version(self):
        for tag in ("1.2.3", "v01.2.3", "v1.2", "v1.2.3-01", "v1.2.3+bad_value", "v1.2.4", "v1.2.3\n"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                validate_tag(tag, self.plugin)
        (self.plugin / "config.h").write_text(
            '#define PLUG_VERSION_STR "1.2.3"\n#define PLUG_VERSION_HEX 0x00010204\n')
        with self.assertRaisesRegex(ValueError, "hex"):
            current_version(self.plugin)

    def test_downloaded_assets_must_match_checksum_version_source_and_architecture(self):
        release = validate_tag("v1.2.3", self.plugin)
        archive = self.package()
        verify_assets(self.root, release, self.sha)
        with self.assertRaisesRegex(ValueError, "source"):
            verify_assets(self.root, release, "b" * 40)
        archive.write_bytes(archive.read_bytes() + b"synthetic tampering")
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_assets(self.root, release, self.sha)
        self.package(manifest_version="1.2.4")
        with self.assertRaisesRegex(ValueError, "version"):
            verify_assets(self.root, release, self.sha)
        self.package(dirty=True)
        with self.assertRaisesRegex(ValueError, "source"):
            verify_assets(self.root, release, self.sha)
        self.package(architecture=0x01000007)
        with self.assertRaisesRegex(ValueError, "arm64"):
            verify_assets(self.root, release, self.sha)

    def test_only_the_exact_tagged_commit_can_be_published(self):
        subprocess.run(["git", "init", "--quiet", "--initial-branch=synthetic-fixture", self.root], check=True)
        git = ["git", "-C", str(self.root), "-c", "user.name=Synthetic fixture",
               "-c", "user.email=synthetic@example.invalid", "-c", "tag.gpgSign=false"]
        environment = {**os.environ, "GIT_AUTHOR_NAME": "Synthetic fixture",
                       "GIT_COMMITTER_NAME": "Synthetic fixture", "GIT_AUTHOR_EMAIL": "synthetic@example.invalid",
                       "GIT_COMMITTER_EMAIL": "synthetic@example.invalid"}
        subprocess.run([*git, "commit", "--quiet", "--allow-empty", "--no-gpg-sign", "-m", "Synthetic release fixture"],
                       check=True, env=environment)
        subprocess.run([*git, "tag", "-a", "v1.2.3", "-m", "Synthetic tag fixture"], check=True, env=environment)
        revision = source_revision(self.root)
        check_tag_revision("v1.2.3", revision, self.root)
        with self.assertRaisesRegex(ValueError, "missing"):
            check_tag_revision("v1.2.4", revision, self.root)
        with self.assertRaisesRegex(ValueError, "revision"):
            check_tag_revision("v1.2.3", "b" * 40, self.root)
        remote = self.root / "synthetic-origin.git"
        subprocess.run(["git", "clone", "--quiet", "--bare", self.root, remote], check=True)
        subprocess.run([*git, "remote", "add", "origin", str(remote)], check=True)
        check_remote_tag("v1.2.3", revision, self.root)
        with self.assertRaisesRegex(ValueError, "remote"):
            check_remote_tag("v1.2.3", "b" * 40, self.root)


if __name__ == "__main__":
    unittest.main()
