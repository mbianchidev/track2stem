#!/usr/bin/env python3
import argparse
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST_COMMIT = "dec3f18dc66bbf1ca3f3e6f13ceff9e1d646a145"


def run(command, **options):
    subprocess.run(list(map(str, command)), check=True, **options)


def main():
    parser = argparse.ArgumentParser(description="Run the real Studio Duo VST3/AU workflow in an isolated offscreen process")
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "plugin/build")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Use native macOS Apple Silicon for the supported host workflow")
    if args.output.exists():
        parser.error("Evidence already exists; choose a new output directory")
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = build / "studio-duo-host"
    if not source.exists():
        with tempfile.TemporaryDirectory(prefix="studio-duo-source-", dir=build) as temporary:
            checkout = Path(temporary) / "host"
            run(["git", "clone", "--filter=blob:none", "--no-checkout",
                 "https://github.com/mbianchidev/studio-duo.git", checkout])
            run(["git", "-C", checkout, "fetch", "--depth=1", "origin", HOST_COMMIT])
            run(["git", "-C", checkout, "checkout", "--detach", HOST_COMMIT])
            checkout.rename(source)
    actual = subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip()
    if actual != HOST_COMMIT:
        raise RuntimeError("The owned test host is not the pinned Studio Duo revision")
    host_build = build / "studio-duo-host-build"
    run(["cmake", "-S", source, "-B", host_build, "-DCMAKE_BUILD_TYPE=Release",
         "-DSTUDIO_DUO_BUILD_TESTS=ON", "-DSTUDIO_DUO_NATIVE_TESTS=ON", "-DCMAKE_OSX_ARCHITECTURES=arm64",
         f"-DCMAKE_PROJECT_StudioDuo_INCLUDE={ROOT / 'plugin/tests/StudioDuoProbe.cmake'}"])
    run(["cmake", "--build", host_build, "--target", "StudioDuoTests", "--parallel", "3"])
    executable = host_build / "StudioDuoTests_artefacts/Release/StudioDuoTests"
    with tempfile.TemporaryDirectory(prefix="track2stem-host-home-", dir=build) as temporary:
        home = Path(temporary)
        (home / "tmp").mkdir()
        environment = {key: value for key, value in os.environ.items()
                       if key in {"PATH", "LANG", "LC_ALL", "SSL_CERT_FILE"}}
        environment.update(HOME=str(home), CFFIXED_USER_HOME=str(home), TMPDIR=str(home / "tmp"))
        if args.plugin.suffix == ".component":
            run(["cmake", "--build", build, "--target", "track2stem-au-registration", "--parallel", "3"])
            environment["DYLD_INSERT_LIBRARIES"] = str(build / "libtrack2stem-au-registration.dylib")
            environment["TRACK2STEM_AU_BUNDLE"] = str(args.plugin.resolve())
        result = subprocess.run([
            executable, "--track2stem-native-workflow", args.plugin.resolve(), args.worker.resolve(),
            args.models.resolve(), args.output.resolve(), args.fixture.resolve(),
        ], env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        print(result.stdout, end="", flush=True)
        result.check_returncode()
    reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    final = next((value for value in reports if value.get("status") == "pass"), None)
    host = next((value for value in reports if value.get("project_package_roundtrip")), None)
    if not final or not host:
        raise RuntimeError("The supported-host workflow did not produce both completion reports")
    (args.output / "host-report.json").write_text(json.dumps(
        {"host_commit": HOST_COMMIT, **host, **final}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
