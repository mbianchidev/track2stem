import os

from PyInstaller.compat import is_darwin
from PyInstaller.depend import dylib
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

if not is_darwin:
    raise RuntimeError("The Track2stem CPU runtime hook supports macOS only")

excludedimports = ["torch.utils.tensorboard"]
# Dependencies found by normal import analysis remain included; these discovery probes are training/export-only.
_discovery_exclusions = (
    "torch.distributed", "torch.testing._internal", "torch.onnx._internal.exporter._torchlib.ops",
    "torch._vendor.quack", "torch._inductor.kernel.vendored_templates.cutedsl",
)
hiddenimports = collect_submodules(
    "torch",
    filter=lambda name: not any(name == prefix or name.startswith(prefix + ".")
                                for prefix in (*excludedimports, *_discovery_exclusions)),
)
datas = collect_data_files("torch", excludes=["**/*.h", "**/*.hpp", "**/*.cuh", "**/*.cpp", "**/*.lib", "**/*.cmake"])
binaries = collect_dynamic_libs("torch")
module_collection_mode = "pyz+py"

_original_exclusions = dylib.exclude_list
_foreign_libraries = {
    "libamdhip64.so", "libhiprtc.so", "libcuda.so.1", "libnvidia-ml.so.1",
    "libc.so.6", "libgomp.so.1", "ntdll", "shell32", "ole32",
}


class DarwinCPULibraries:
    def check_library(self, name):
        return os.path.basename(name) in _foreign_libraries or _original_exclusions.check_library(name)


# Foreign driver/OS branches are not macOS dependencies; unknown missing libraries still warn.
dylib.exclude_list = DarwinCPULibraries()
