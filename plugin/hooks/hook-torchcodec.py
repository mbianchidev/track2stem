from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata, get_package_paths

_, package = get_package_paths("torchcodec")
datas = collect_data_files("torchcodec", include_py_files=True, excludes=["**/*.dylib"])
datas += copy_metadata("torchcodec")
hiddenimports = collect_submodules("torchcodec")
binaries = [(str(path), "torchcodec") for path in Path(package).glob("*.dylib")
            if path.name.endswith("9.dylib") or path.name in {
                "libtorchcodec_image.dylib", "libtorchcodec_pybind_ops.dylib",
            }]
if not binaries:
    raise RuntimeError("The native runtime requires TorchCodec's FFmpeg 9 libraries")
