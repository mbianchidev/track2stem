import plistlib
import shutil
from pathlib import Path


def install_package(package, home):
    package = Path(package).resolve()
    home = Path(home).resolve()
    products = (
        ("Track2stem.vst3", home / "Library/Audio/Plug-Ins/VST3/Track2stem.vst3",
         "dev.track2stem.vst3.Track2stem"),
        ("Track2stem.component", home / "Library/Audio/Plug-Ins/Components/Track2stem.component",
         "dev.track2stem.audiounit.Track2stem"),
        ("Runtime", home / "Library/Application Support/Track2stem/Runtime", None),
    )
    for name, target, identifier in products:
        source = package / name
        if not source.is_dir() or source.is_symlink():
            raise ValueError(f"The installation package is incomplete: {name}")
        if identifier:
            with (source / "Contents/Info.plist").open("rb") as data:
                metadata = plistlib.load(data)
            if metadata.get("CFBundleIdentifier") != identifier:
                raise ValueError(f"Unexpected plugin identity in {name}")
        elif not (source / "track2stem-worker").is_file():
            raise ValueError("The bundled native runtime is missing")
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"{target} already exists. Quit your DAW and move the previous installation aside before retrying. Audio and model caches must be kept.")
    created = []
    try:
        for name, target, _identifier in products:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.mkdir(exist_ok=False)
            created.append(target)
            shutil.copytree(package / name, target, dirs_exist_ok=True, symlinks=True)
    except OSError:
        for target in reversed(created):
            shutil.rmtree(target)
        raise
    return [str(target) for target in created]
