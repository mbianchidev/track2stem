import plistlib
from pathlib import Path

import pytest

from track2stem_engine.installation import install_package


def package_fixture(tmp_path):
    package = tmp_path / "package"
    for extension, identifier in (("vst3", "dev.track2stem.vst3.Track2stem"),
                                  ("component", "dev.track2stem.audiounit.Track2stem")):
        contents = package / f"Track2stem.{extension}" / "Contents"
        contents.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as target:
            plistlib.dump({"CFBundleIdentifier": identifier}, target)
        (contents / "synthetic.bin").write_bytes(b"synthetic plugin fixture")
    runtime = package / "Runtime"
    runtime.mkdir()
    (runtime / "track2stem-worker").write_bytes(b"synthetic worker fixture")
    (runtime / "track2stem-worker").chmod(0o755)
    return package


def test_installation_preserves_audio_and_refuses_existing_plugins(tmp_path):
    package = package_fixture(tmp_path)
    home = tmp_path / "home"
    audio = home / "Library/Application Support/Track2stem/Data/retained.wav"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"synthetic retained audio")
    targets = install_package(package, home)
    assert len(targets) == 3
    assert all(Path(path).exists() for path in targets)
    assert audio.read_bytes() == b"synthetic retained audio"
    with pytest.raises(FileExistsError, match="already exists"):
        install_package(package, home)
    assert audio.exists()


def test_failed_installation_removes_only_new_owned_targets(tmp_path, monkeypatch):
    import shutil

    package = package_fixture(tmp_path)
    home = tmp_path / "home"
    retained = home / "Library/Application Support/Track2stem/Data/keep.txt"
    retained.parent.mkdir(parents=True)
    retained.write_text("synthetic retained data")
    original = shutil.copytree

    def fail_component(source, target, *args, **kwargs):
        if Path(source).name == "Track2stem.component":
            raise OSError("Synthetic copy failure")
        return original(source, target, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", fail_component)
    with pytest.raises(OSError, match="Synthetic copy failure"):
        install_package(package, home)
    assert retained.read_text() == "synthetic retained data"
    assert not (home / "Library/Audio/Plug-Ins/VST3/Track2stem.vst3").exists()
    assert not (home / "Library/Audio/Plug-Ins/Components/Track2stem.component").exists()
