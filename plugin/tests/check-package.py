#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Verify a native ZIP and install it into an isolated temporary home")
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64":
        parser.error("Verify native Apple Silicon packages on macOS")
    archive = args.archive.resolve()
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    expected, filename = archive.with_suffix(".zip.sha256").read_text().strip().split(maxsplit=1)
    assert digest == expected and filename == archive.name, "Package checksum does not match"
    with tempfile.TemporaryDirectory(prefix="track2stem-package-install-") as temporary:
        root = Path(temporary)
        extracted = root / "extracted"
        subprocess.run(["ditto", "-x", "-k", archive, extracted], check=True)
        package = extracted / archive.stem
        report = json.loads((package / "BuildInfo.json").read_text())
        assert report["models_bundled"] is False
        assert report["runtime_audit"]["external_library_references"] == []
        for name in ("CPython-LICENSE.txt", "OpenSSL-LICENSE.txt", "Track2stem-LICENSE.txt",
                     "iPlug2-LICENSE.txt", "iPlug2-WebView-LICENSE.txt", "VST3-SDK-LICENSE.txt",
                     "LAME-COPYING.txt", "FFmpeg-COPYING.LGPLv2.1", "Node-LICENSE.txt"):
            assert (package / "Notices" / name).stat().st_size > 100, name
        sources = package / "ThirdPartySources"
        pins = json.loads((sources / "native-dependencies.json").read_text())
        for name in ("ffmpeg", "lame", "pyav"):
            with (sources / pins[name]["archive"]).open("rb") as source:
                assert hashlib.file_digest(source, "sha256").hexdigest() == pins[name]["sha256"], name
        assert (sources / "patches/webview.patch").is_file()
        assert (sources / "CMakeLists.txt").is_file()
        home = root / "home"
        data = home / "Library/Application Support/Track2stem/Data"
        models = home / "Library/Caches/Track2stem/models"
        for directory in (data, models):
            directory.mkdir(parents=True)
            (directory / "retained-fixture.txt").write_text("synthetic retained data", encoding="ascii")
        environment = {key: value for key, value in os.environ.items()
                       if key not in {"PYTHONPATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "VIRTUAL_ENV"}
                       and not key.startswith("TRACK2STEM_")}
        environment.update(HOME=str(home), PATH="/usr/bin:/bin:/usr/sbin:/sbin")
        installer = package / "Install.command"
        subprocess.run([installer], check=True, env=environment)
        products = (
            (home / "Library/Audio/Plug-Ins/VST3/Track2stem.vst3", "dev.track2stem.vst3.Track2stem"),
            (home / "Library/Audio/Plug-Ins/Components/Track2stem.component", "dev.track2stem.audiounit.Track2stem"),
        )
        for product, identifier in products:
            with (product / "Contents/Info.plist").open("rb") as source:
                assert plistlib.load(source)["CFBundleIdentifier"] == identifier
            subprocess.run(["codesign", "--verify", "--strict", product], check=True)
            web = product / "Contents/Resources/web"
            assert (web / "index.html").is_file()
            assert len(list((web / "font-licenses").glob("*.txt"))) == 3
        worker = home / "Library/Application Support/Track2stem/Runtime/track2stem-worker"
        result = json.loads(subprocess.check_output(
            [worker, "--root", data, "--models", models, "--self-test"], env=environment, text=True))
        assert result["cpu_only"] is True and result["flask_loaded"] is False
        assert result["python_version"] == report["runtime"]["python_version"]
        second = subprocess.run([installer], env=environment, capture_output=True, text=True)
        assert second.returncode != 0 and "already exists" in second.stderr, second.stdout + second.stderr
        for directory in (data, models):
            assert (directory / "retained-fixture.txt").read_text() == "synthetic retained data"
    print(json.dumps({"status": "pass", "checksum": digest, "isolated_home": True,
                      "no_host_runtime": True, "refuses_overwrite": True, "preserves_data": True}))


if __name__ == "__main__":
    main()
