#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import platform
import shutil
import shlex
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugin"


def run(command, cwd=ROOT, env=None):
    print(f"[native] {' '.join(map(str, command))}", flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def dependency(name, pins, build):
    pin = pins[name]
    archive = build / "downloads" / pin["archive"]
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix(archive.suffix + ".part")
        try:
            with urllib.request.urlopen(pin["url"], timeout=30) as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != pin["sha256"]:
        raise RuntimeError(f"Checksum mismatch: {archive}")
    directory = build / "runtime-sources" / pin["directory"]
    marker = directory / ".track2stem-source-ready"
    if not marker.exists():
        if directory.is_symlink():
            raise RuntimeError(f"Refusing a symlink source directory: {directory}")
        if directory.exists():
            shutil.rmtree(directory)
        directory.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as source:
            source.extractall(directory.parent, filter="data")
        marker.write_text(pin["sha256"], encoding="ascii")
    return directory, archive


def build_codecs(pins, build, workers):
    prefix = build / "codecs"
    marker = prefix / ".track2stem-codecs-ready"
    fingerprint = hashlib.sha256(json.dumps(pins, sort_keys=True).encode() + Path(__file__).read_bytes()).hexdigest()
    lame, _ = dependency("lame", pins, build)
    ffmpeg, _ = dependency("ffmpeg", pins, build)
    if marker.exists() and marker.read_text() == fingerprint:
        return prefix
    environment = {**os.environ,
                   "CFLAGS": "-O2 -mmacosx-version-min=14.0",
                   "LDFLAGS": "-mmacosx-version-min=14.0",
                   "PKG_CONFIG_PATH": str(prefix / "lib/pkgconfig")}
    run([lame / "configure", f"--prefix={prefix}", "--disable-shared", "--enable-static",
         "--disable-frontend", "--disable-decoder", "--with-pic"], cwd=lame, env=environment)
    run(["make", f"-j{workers}"], cwd=lame, env=environment)
    run(["make", "install"], cwd=lame, env=environment)
    run([
        ffmpeg / "configure", f"--prefix={prefix}", "--arch=arm64", "--target-os=darwin",
        "--enable-shared", "--disable-static", "--disable-gpl", "--disable-nonfree",
        "--disable-doc", "--disable-debug", "--disable-autodetect", "--disable-everything",
        "--enable-ffmpeg", "--enable-ffprobe", "--enable-libmp3lame",
        "--enable-protocol=file,pipe",
        "--enable-demuxer=wav,mp3,flac,ogg,mov,aac,matroska",
        "--enable-parser=aac,aac_latm,flac,mpegaudio,opus,vorbis",
        "--enable-decoder=aac,aac_fixed,alac,flac,mp3,mp3float,opus,vorbis,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_s32be,pcm_f32le,pcm_f32be,pcm_f64le,pcm_f64be,pcm_u8",
        "--enable-encoder=pcm_f32le,pcm_s16le,flac,libmp3lame",
        "--enable-muxer=wav,flac,mp3",
        "--enable-filter=aformat,aresample,anull,amix,volume,atrim,asetpts",
        f"--extra-cflags=-mmacosx-version-min=14.0 -I{shlex.quote(str(prefix / 'include'))}",
        f"--extra-ldflags=-mmacosx-version-min=14.0 -L{shlex.quote(str(prefix / 'lib'))}",
        "--install-name-dir=@rpath",
    ], cwd=ffmpeg, env=environment)
    run(["make", f"-j{workers}"], cwd=ffmpeg, env=environment)
    run(["make", "install"], cwd=ffmpeg, env=environment)
    license_text = subprocess.check_output([prefix / "bin/ffmpeg", "-L"], env={
        **environment, "DYLD_LIBRARY_PATH": str(prefix / "lib"),
    }, text=True, stderr=subprocess.STDOUT)
    normalized_license = " ".join(license_text.split())
    if "GNU Lesser General Public License" not in normalized_license or "--enable-gpl" in license_text:
        raise RuntimeError("The distributable FFmpeg build must be LGPL-only")
    marker.write_text(fingerprint, encoding="ascii")
    return prefix


def main():
    parser = argparse.ArgumentParser(description="Build the self-contained Apple Silicon CPU worker")
    parser.add_argument("--build-dir", type=Path, default=PLUGIN / "build")
    parser.add_argument("--workers", type=int, default=min(6, os.process_cpu_count() or 1))
    args = parser.parse_args()
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 14):
        parser.error("Use native macOS Apple Silicon with Python 3.14")
    if not 1 <= args.workers <= (os.process_cpu_count() or 1):
        parser.error("Worker count must fit the host CPU count")
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    pins = json.loads((PLUGIN / "native-dependencies.json").read_text())
    codecs = build_codecs(pins, build, args.workers)
    node, _ = dependency("node", pins, build)
    standalone, _ = dependency("python", pins, build)
    environment = build / f"runtime-venv-{pins['python']['version']}"
    python = environment / "bin/python"
    if not python.exists():
        run([standalone / "bin/python3.14", "-m", "venv", environment])
    manifests = (PLUGIN / "requirements-build.txt", ROOT / "processor/requirements.txt")
    fingerprint = hashlib.sha256(b"".join(path.read_bytes() for path in manifests)).hexdigest()
    marker = environment / ".track2stem-requirements"
    if not marker.exists() or marker.read_text() != fingerprint:
        run([python, "-m", "pip", "install", "-r", PLUGIN / "requirements-build.txt"])
        marker.write_text(fingerprint, encoding="ascii")
    run([python, "-m", "pip", "check"])
    pyav, _ = dependency("pyav", pins, build)
    av_marker = environment / ".track2stem-source-pyav"
    if not av_marker.exists() or av_marker.read_text() != pins["pyav"]["sha256"]:
        run([python, "-m", "pip", "install", "--no-deps", "--force-reinstall", pyav],
            env={**os.environ, "PKG_CONFIG_PATH": str(codecs / "lib/pkgconfig"),
                 "CFLAGS": "-O2 -mmacosx-version-min=14.0",
                 "LDFLAGS": f"-mmacosx-version-min=14.0 -Wl,-rpath,{codecs / 'lib'}"})
        av_marker.write_text(pins["pyav"]["sha256"], encoding="ascii")
    command = [
        python, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
        "--name", "track2stem-worker", "--target-arch", "arm64",
        "--distpath", build / "runtime-dist", "--workpath", build / "pyinstaller",
        "--specpath", build / "pyinstaller-spec", "--paths", ROOT / "processor",
        "--additional-hooks-dir", PLUGIN / "hooks",
        "--add-binary", f"{codecs / 'bin/ffmpeg'}:.",
        "--add-binary", f"{codecs / 'bin/ffprobe'}:.",
        "--add-binary", f"{node / 'bin/node'}:.",
        "--exclude-module", "pytest", "--exclude-module", "IPython",
        "--exclude-module", "matplotlib", "--exclude-module", "tkinter",
    ]
    for library in sorted((codecs / "lib").glob("*.dylib")):
        command.extend(["--add-binary", f"{library}:."])
    for package in ("demucs", "dora", "torchaudio", "faster_whisper", "beat_this",
                    "safetensors", "asteroid_filterbanks", "sklearn",
                    "ctranslate2", "onnxruntime", "librosa", "yt_dlp", "yt_dlp_ejs", "av"):
        command.extend(["--collect-all", package])
    command.extend(["--copy-metadata", "torch", ROOT / "processor/worker_entry.py"])
    run(command, env={**os.environ, "DYLD_LIBRARY_PATH": str(codecs / "lib")})
    runtime = build / "runtime-dist/track2stem-worker"
    run([python, PLUGIN / "audit-runtime.py", runtime, "--prune-unused-libraries",
         "--output", build / "runtime-dist/RuntimeAudit.json"])
    sources = build / "runtime-dist/ThirdPartySources"
    sources.mkdir(exist_ok=True)
    for name in ("ffmpeg", "lame", "pyav"):
        shutil.copy2(build / "downloads" / pins[name]["archive"], sources)
    shutil.copytree(ROOT / "processor/drum_transcriber", sources / "ADT_STR_CPU",
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "processor/track2stem_engine/third_party", sources / "VocalInference",
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(PLUGIN / "native-dependencies.json", sources)
    shutil.copy2(PLUGIN / "build-runtime.py", sources)
    notices = build / "runtime-dist/Notices"
    notices.mkdir(exist_ok=True)
    shutil.copy2(node / "LICENSE", notices / "Node-LICENSE.txt")
    shutil.copy2(ROOT / "processor/drum_transcriber/LICENSE", notices / "ADT_STR-CPU-CC-BY-SA-4.0.txt")
    for name in ("ASTEROID-LICENSE", "MEDLEYVOX-MODEL-LICENSE"):
        shutil.copy2(ROOT / "processor/track2stem_engine/third_party" / name, notices / f"{name}.txt")
    for location in ("licenses", "share/licenses"):
        if (standalone / location).is_dir():
            shutil.copytree(standalone / location, notices / "Python-runtime", dirs_exist_ok=True)
    shutil.copy2(build / "runtime-sources" / pins["lame"]["directory"] / "COPYING", notices / "LAME-COPYING.txt")
    shutil.copy2(build / "runtime-sources" / pins["ffmpeg"]["directory"] / "COPYING.LGPLv2.1", notices / "FFmpeg-COPYING.LGPLv2.1")
    run([python, PLUGIN / "collect-notices.py", notices / "Python-dependencies"])
    run([runtime / "track2stem-worker", "--root", build / "self-test-data",
         "--models", build / "self-test-models", "--self-test"],
        env={key: value for key, value in os.environ.items()
             if key not in {"PYTHONPATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH", "VIRTUAL_ENV"}})
    print(f"Native worker ready: {runtime}", flush=True)


if __name__ == "__main__":
    main()
