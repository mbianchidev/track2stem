# Native DAW plugin

[Documentation index](README.md) | [Usage](usage.md) | [Development](development.md)

Track2stem has independent **VST3** and **Audio Unit v2** targets for **macOS Apple Silicon**. The first workflow is offline file import, background separation and stem export. It does not capture DAW input, create DAW tracks automatically, or perform low-latency separation. The audited binary deployment floor is macOS 14.0; host workflow evidence currently covers macOS 26.6 only.

The audio callback is a zero-latency pass-through. Inference, decoding, conversion, HTTP communication and file writes run outside that callback, in an automatically launched, bundled CPU worker. No browser, Docker, separately installed Python, or manually started server is required after installation.

## Install a package

Native builds are currently development artifacts, not a signed/notarized public release. Build from the repository using the instructions below, or use an artifact whose origin and SHA-256 checksum you have verified. Never disable Gatekeeper globally or bypass a malware warning.

1. Extract the complete `Track2stem-0.1.0-macos-arm64-*.zip`, preserving its symlinks.
2. Quit the DAW, then run `Install.command` from the extracted folder.
3. Open the DAW and scan for **Track2stem**. Choose VST3 or AU, not both in the same insert.
4. Open its editor, select an authorized audio file, choose separation settings, and process it. First use of a model downloads its weights; audio stays local.
5. Use the stem download controls to choose an export destination through the native save dialog. Missing cached audio, cancelled dialogs and failed writes are reported in the editor; an HTTP error is never presented as a successful audio export.

The installer refuses existing installations rather than overwriting them. For an update, quit the DAW and move the previous plugin bundles and `Runtime` directory aside before installing again. Keep `Data` and model caches if their processed audio is still referenced by projects.

| Product | Per-user destination |
|---------|----------------------|
| VST3 | `~/Library/Audio/Plug-Ins/VST3/Track2stem.vst3` |
| AUv2 | `~/Library/Audio/Plug-Ins/Components/Track2stem.component` |
| Shared worker | `~/Library/Application Support/Track2stem/Runtime/track2stem-worker` |
| Processed audio | `~/Library/Application Support/Track2stem/Data/outputs/` |
| Model cache | `~/Library/Caches/Track2stem/models/` |

No system-wide plugin folder is modified. Installation preserves existing audio/model data and rolls back only newly created product directories if a copy fails. The packages use ad-hoc signatures, not Developer ID signatures or Apple notarization.

## Project save and recovery

The plugin stores a versioned settings and job-reference snapshot in the DAW's opaque plugin state. This is separate from browser localStorage. It includes separation settings, enabled practice tools, recent/current job metadata, and mix gains. Large note/lyric arrays are not copied into history; the worker retains the actual artifacts. **Save the DAW project explicitly.**

Audio and model weights are not embedded in the DAW project. Reopening resolves job IDs against the local data directory and uses the latest stored render for each job. Selected input files and interrupted inference are not resumed automatically. Missing processed files produce an actionable error asking for another import; missing uncached models require provisioning before offline use.

Keep the data directory when moving between plugin versions. Export stems separately before moving a project to another machine. Render versions are retained to preserve in-flight downloads; there is no automatic expiration. Removing browser/DAW history does not delete audio.

Cancelling is cooperative between model windows and during conversion. Closing only the editor leaves its background job running. Removing the plugin stops its owned worker process group; an unresponsive worker is terminated after a bounded grace period. The worker also watches its owning host and stops if that parent disappears. Forced termination can leave an incomplete cache directory, but it never marks that job completed or removes a caller-owned source file.

## Support and evidence

| Target | Current evidence |
|--------|------------------|
| macOS 26.6, arm64, Studio Duo 1.7.6, VST3 | The isolated Studio Duo native probe loads the real bundle, processes synthetic audio, round-trips opaque state, and creates its editor. |
| macOS 26.6, arm64, Studio Duo 1.7.6, AUv2 | The same probe passes using process-local AU registration, without changing the user's plugin catalog. |
| Packaged local worker | Real synthetic inference verifies six PCM16 WAV stems, FLAC lead/backing vocals plus instrumental, 320-kbps MP3 isolation/backing, practice artifacts and remixing. |
| Package installation | The ZIP checksum, dependency sources/notices, signatures and installed CPU runtime are checked in an isolated temporary home with a minimal system-only PATH. Reinstallation is refused and synthetic existing data/model-cache markers are preserved. |
| Offscreen native editor | The real AU editor launches its bundled worker, imports generated audio, exports through the native adapter, reports missing files and cancellation/write errors, cancels processing, saves/reopens project state, and survives an injected worker crash while rendering unchanged synthetic audio. Only the OS save-dialog selection is replaced by a test double; no user workspace or audio device is opened. |
| Other DAWs, Intel macOS, Windows, Linux-native plugins, Apple App Sandbox | Not qualified or supported by this initial target. Web deployment remains separate. |

These are automated checks, not a certification of every vendor mode, physical audio deadline, accessibility workflow, or long-running session. The Studio Duo reports deliberately retain `qualificationStatus: not-qualified`; a basic probe is not a full release sign-off. `BuildInfo.json` records the runtime's actual deployment targets and absence of machine-local library references. A macOS 14.0 deployment target is not evidence that older hosts have been qualified.

Studio Duo's generic extended-effect workflow requires a continuous automatable control and stops at that precondition for this offline utility, which exposes only host bypass. The native-specific import/export, cancellation, recovery and pass-through checks use the separate offscreen editor probe instead; the generic workflow is not reported as passing.

## Build independently of the web stack

Use native Apple Silicon, Python 3.14, Node.js 26.12.1, Xcode Command Line Tools, CMake, Make, and pkg-config. The Go service and Docker are not build prerequisites.

```bash
bash plugin/build.sh
```

The script provisions checksum-pinned standalone Python 3.14.9 into the build directory, installs declared dependencies in its isolated runtime environment, builds an LGPL-only FFmpeg/LAME stack, compiles PyAV against those libraries, freezes the Python worker, builds the shared React UI with local fonts, compiles the VST3/AU wrappers, and writes a timestamped ZIP plus SHA-256 file under `plugin/dist/`. It does not install plugins or publish a release.

Builds fetch pinned iPlug2 and VST3 SDK revisions into the ignored build directory. Automatic SDK deployment into the user's Library is disabled. A small WebView patch prevents double navigation callbacks, treats a cancelled save dialog as cancellation, rejects HTTP export errors, and uses WebKit's actual failure-callback selector. A Mach-O audit rejects machine-local library references and records the deployment floor. Model weights are not bundled.

For focused wrapper development:

```bash
cd frontend
npm ci
npm run build -- --base=./ --outDir ../plugin/build/web --emptyOutDir
cd ..
cmake -S plugin -B plugin/build -DCMAKE_BUILD_TYPE=Release
cmake --build plugin/build --target Track2stem-vst3 Track2stem-au --parallel 4
```

For a real frozen-worker check, provide an existing model cache or permit first-use downloads, and a new evidence directory:

```bash
python3.14 plugin/tests/check-worker.py \
  --worker "$PWD/plugin/build/runtime-dist/track2stem-worker/track2stem-worker" \
  --models "$HOME/Library/Caches/Track2stem/models" \
  --ui "$PWD/plugin/build/web" \
  --output "$PWD/plugin/build/worker-evidence"
```

Verify a ZIP without installing into your actual Library:

```bash
python3.14 plugin/tests/check-package.py plugin/dist/Track2stem-0.1.0-macos-arm64-BUILD.zip
```

Replace `BUILD` with the generated artifact's timestamp. The check extracts into a temporary directory, runs the actual installer twice with an isolated home, and cleans up its own installation afterward.

Native debugging can override `TRACK2STEM_WORKER`, `TRACK2STEM_DATA_DIR` and `TRACK2STEM_MODELS_DIR` before starting an isolated host. Worker logs are written under the selected data root. Do not point qualification tools at a user's live project or alter their global plugin catalog.

## Runtime and dependency licenses

Track2stem's own code remains MIT. iPlug2 uses a zlib-like license; its WebView component and the VST3 SDK are MIT. Their original notices and the applied patch remain part of the build/package evidence.

The distribution includes separate notices for Python dependencies, Node.js, CPython, and the fonts. FFmpeg is built with GPL and nonfree components disabled, using LGPL LAME and a source-built PyAV. Corresponding FFmpeg/LAME/PyAV source archives, checksums and build instructions accompany the package. The LGPL libraries remain replaceable; rebuilding modified binaries may require local ad-hoc signing.

Model weights are fetched separately under upstream terms. In particular, the UVR karaoke download lacks a clear model-specific redistribution license. Do not redistribute those weights or claim that this repository's MIT license grants commercial model rights. See [model downloads](configuration.md#model-downloads).
