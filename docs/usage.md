# Usage

[Documentation index](README.md) | [Configuration](configuration.md) | [Troubleshooting](troubleshooting.md)

## Separate a track

1. Start the stack using the [quickstart](../README.md#quickstart) and open http://localhost:3000.
2. Click **Choose audio file** in **Source audio**. Supported extensions are MP3, WAV, FLAC, OGG, M4A, and AAC, up to 100 MiB. Alternatively, select **YouTube link** and enter a single video URL.
3. In **Separation settings**, choose **All 6 stems / All 4 stems** or **Isolate one**, then select the model and output format.
4. Click **Upload & Process**. **Separated stems** shows the current job, processing stage, progress, and elapsed time.
5. When completed, click **Download** beside each stem's waveform, or use the download controls in **Recent jobs**.

On desktop, the source and output lanes sit beside the settings panel. On narrow screens, the same controls stack in workflow order. To replace a selected source, click **Choose audio file** again.

Output filenames include the sanitized original track name and stem, such as `song_t2s_vocals.mp3`.

## Models and stems

| Model | Available stems |
|-------|-----------------|
| `htdemucs_6s` (default) | Vocals, drums, bass, guitar, piano, other |
| `htdemucs`, `htdemucs_ft`, `hdemucs_mmi`, `mdx`, `mdx_extra`, `mdx_q`, `mdx_extra_q` | Vocals, drums, bass, other |

Guitar and piano isolation require `htdemucs_6s`. Switching to a four-stem model while either is selected resets isolation to vocals and displays an explanation. In isolate mode, vocals produce `vocals` and `instrumental`; another instrument produces that stem and `backing`.

Isolate mode still separates the full track before mixing the remaining stems. It is not a faster two-stem inference path. The API also accepts `other` as an isolated stem, though the browser's selector does not offer it.

The **Fast / four stems** CPU profile selects `htdemucs`, disables shift passes, and reduces overlap to `0.1`. It sacrifices separate guitar/piano outputs and some boundary overlap. **Six-stem defaults** restores the default model and overlap. Neither profile is a processing-time guarantee.

## Instrument levels

Completed jobs expose a slider for each original instrument, including the instruments inside `backing` or `instrumental`. The default is **100%**, with a range of **0-400%**: zero mutes, 200% is approximately +6 dB, and 400% is approximately +12 dB.

**Play mix** previews the original lossless stems in sync, with live level changes. **Stop** ends playback. Boosts can clip the browser preview. **Export mix** regenerates downloads without rerunning separation; the selected rescale/clamp policy applies to exports. If export fails, previous downloads remain available. Reset levels returns every instrument to 100%.

## Practice tools

Enable only the tools needed before processing. Everything runs locally on CPU; uncached model weights require an initial download.

| Tool | Output and limitations |
|------|------------------------|
| Tempo, key & song sections | Time-varying beat grid, tempo CSV, key estimate, possible drop-tuning evidence from guitar/bass, and timed section estimates. Section labels use repetition, energy and stem activity, not semantic certainty. |
| Click track | Stereo WAV click following the detected beat grid, including tempo changes. Accents assume 4/4; half/double-tempo ambiguity is possible. |
| Lyrics | Whisper base transcription of the vocal stem, with text, SRT subtitles and word-timing JSON. Singing and overlapping vocals can reduce accuracy; instrumental audio may produce no words. |
| Guitar tabs / Bass tabs | Basic Pitch CPU note estimates, proposed string/fret assignments, text tabs, MusicXML scores, MIDI and JSON. Guitar requires the six-stem model. Open MusicXML in a compatible Guitar Pro or notation editor and review rhythm, notes and tuning. |
| Drum tabs & MIDI | Transient/band-based kick, snare and closed-hi-hat estimates, text/percussion MusicXML, General MIDI channel-10 events, and JSON. The MIDI uses the same detected hits as the drum tabs. This is not a full drum-kit classifier. |
| Lead / backing vocals | A second local karaoke model separates the vocal stem into `lead_vocals` and `backing_vocals`. In vocal-isolate mode, these appear beside `instrumental`. Separation is approximate and can contain bleed. |

Tabs and MIDI use the detected tempo map when analysis is enabled; otherwise, a 120 BPM reference clock preserves note timings in seconds. Meter is assumed to be 4/4. Tuning and fingerings are proposals, not a uniquely identifiable property of a recording. Unassignable pitches remain in MIDI/JSON and are explicitly marked in the text export.

The [model and runtime notes](configuration.md#model-downloads) describe caching and upstream weight licenses. Automatic analysis and transcriptions need human review.

## YouTube imports

Select **YouTube link**, provide an HTTPS `youtube.com/watch`, `youtube.com/shorts`, or `youtu.be` video URL, then click **Import & Process**. Imports support single, non-live videos up to 60 minutes and 100 MiB of downloaded media, with a ten-minute import deadline. Audio is downloaded and converted locally; it is not sent to a separation service.

Only import material you have permission to use. Playlists, arbitrary websites, browser cookies, login bypasses and DRM bypasses are not supported. Restricted videos or upstream extractor changes can prevent import; upload an authorized local audio file instead. The container includes Node.js for yt-dlp's YouTube JavaScript challenges.

## Output formats

| Format | Behavior |
|--------|----------|
| MP3 (default) | FFmpeg encodes 320 kbps MP3 from lossless internal stems |
| WAV | Stereo 44.1 kHz 16-bit PCM |
| FLAC | Lossless stereo 44.1 kHz, encoded from internal float WAV stems |

## Advanced tuning

The **Advanced tuning** control expands these options inside **Separation settings**. The processor validates the listed values, but Demucs may reject settings that are incompatible with the chosen model.

| Setting | Browser default | Accepted values |
|---------|-----------------|-----------------|
| Segment size | Default (model limit) | No override, 5 or 7 seconds; non-Transformer models also offer 8, 10, 15, 20, 25, 30, 40, 60 |
| Overlap | `0.25` | No override, or `0.1`, `0.15`, `0.2`, `0.25`, `0.3`, `0.35`, `0.4`, `0.5` |
| Shifts | `0` | API accepts integers 0 through 10; the browser offers 0, 1, 2, 5, 10 |
| Clip mode | `rescale` | `rescale` or `clamp` |
| Parallel CPU workers | `1` | Integers 1 through 4, not exceeding the processor's available CPU count |

Leave segment size at **Default** initially. Larger overlap, additional shifts, and fine-tuned models can increase processing time.

Zero shifts now explicitly disables shift augmentation. A long-lived engine keeps one selected Demucs model in memory, and bounded workers reuse it across overlapping segments. Reassembly uses weighted overlap-add rather than concatenation. More workers increase memory use and do not guarantee faster processing on every host.

Transformer models reject segment overrides above their trained limit. Use **Default**, 5 or 7 seconds rather than the legacy 8-second override.

## Progress, previews, and history

The browser polls job status and processor progress every two seconds. Separation progress counts completed segments; optional tools and exports have separate stages. It is not a remaining-time forecast.

The component named `Spectrogram` draws amplitude waveforms, not frequency spectrograms. Browser audio decoding support determines which formats can be previewed; a failed waveform does not necessarily mean the processor cannot read the file. Waveform errors do not remove the download controls.

Recent-job metadata, the current job, and its timer are saved in browser localStorage for refresh recovery. The backend job map is separate and only lives in memory. See [data lifecycle](configuration.md#limitations-and-data-lifecycle) before restarting services or relying on old downloads.

**Recent jobs** shows up to ten entries. **Clear** dismisses a completed or failed current job without removing its history entry. **Remove from history** removes the browser metadata; it does not delete stored audio. For an active history entry, removal also requests cancellation through job deletion. This is [best-effort](configuration.md#limitations-and-data-lifecycle), not a guarantee that all processing stages stop immediately.
