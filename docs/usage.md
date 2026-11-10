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

The **Fast / four stems** CPU profile selects the convolutional Hybrid v3 model `hdemucs_mmi`, bounds its windows to seven seconds, disables shift passes, and reduces overlap to `0.1`. Bounding the convolutional model's otherwise long default segment avoids its large memory cost. The profile sacrifices separate guitar/piano outputs and some boundary overlap; separation quality differs from the Transformer models. **Six-stem defaults** restores the default model, segment and overlap. Neither profile is a processing-time guarantee.

## Instrument levels

Completed jobs expose a slider for each original instrument, including the instruments inside `backing` or `instrumental`. The default is **100%**, with a range of **0-400%**: zero mutes, 200% is approximately +6 dB, and 400% is approximately +12 dB.

**Play mix** previews the original lossless stems in sync, with live level changes. **Stop** ends playback. Boosts can clip the browser preview. **Export mix** regenerates downloads without rerunning separation; the selected rescale/clamp policy applies to exports. If export fails, previous downloads remain available. Reset levels returns every instrument to 100%.

## Practice tools

Enable only the tools needed before processing. Everything runs locally on CPU; uncached model weights require an initial download.

| Tool | Output and limitations |
|------|------------------------|
| Tempo, key & song sections | Neural beat/downbeat tracking, tempo and meter CSVs, key estimate, whole-track guitar/bass tuning candidates, and timed section estimates. Section labels use repetition, energy and stem activity, not semantic certainty. |
| Click track | Stereo WAV click following the detected beat grid and downbeats, including tempo and meter changes. Unknown meter produces unaccented clicks, not a forced four-beat pattern. Half/double-tempo and denominator ambiguity remain possible. |
| Lyrics | Whisper large-v3-turbo CPU transcription of the vocal stem, with text, SRT subtitles and word-timing JSON. Sustained singing is not removed by speech-only VAD; unreliable no-speech segments are excluded. Singing and overlapping vocals can still reduce accuracy. |
| Guitar tabs / Bass tabs | Basic Pitch CPU note estimates, proposed string/fret assignments, text tabs, MusicXML scores, MIDI and JSON. Guitar requires the six-stem model. Open MusicXML in a compatible Guitar Pro or notation editor and review rhythm, notes and tuning. |
| Drum tabs & MIDI | An isolated ADT_STR CPU model estimates 26 percussion classes, including toms, ride, crashes and open/closed/pedal hats. Text, percussion MusicXML, General MIDI channel-10 events and JSON use the same detected hits. Class-level validation is ongoing; predictions are not a guaranteed acoustic-kit score. |
| Lead / backing vocals | Adaptive local separation produces `lead_vocals` and `backing_vocals`; vocal-isolate mode also includes `instrumental`. Identifiable stereo uses spatial unmixing without weights; mono or rank-deficient audio uses the explicitly licensed MedleyVox neural model. The dominant global stream is proposed as lead, not guaranteed to be the artistic lead. Results can contain bleed. |

Tab requests automatically obtain beat/meter timing, even if the full key/section analysis is not enabled. MIDI and MusicXML preserve detected time-signature changes; uncertain meter is written as unmetered notation. Tempo maps use quarter-note BPM, so six eighth-note pulses at 120 pulses/minute become 60 quarter-note BPM in 6/8. Review ambiguous metrical interpretations.

Vocal details include the selected method, model provenance and ambiguity warnings. Spatial separation assumes at most two approximately independent groups with fixed, distinct stereo positions; changing pans, reverberation and more voices can violate that assumption. `TRACK2STEM_VOCAL_METHOD=neural` selects the neural alternative explicitly; forced `spatial` rejects mono/unidentifiable input rather than pretending to split it. Mono separation remains approximate and has not demonstrated a quality gain on the controlled synthetic singing reference.

Tuning inference examines the entire guitar/bass stem in bounded windows rather than only its introduction. It ranks supported standard, drop and extended-range tunings using stable pitch duration, multiple open-string matches and playable fret ranges. A lowest note alone cannot establish tuning. Ambiguous cases retain alternatives and are marked as such; notation uses an explicitly proposed fingering. Unassignable pitches remain in MIDI/JSON and are marked in the text export.

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
