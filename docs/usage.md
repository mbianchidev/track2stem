# Usage

[Documentation index](README.md) | [Configuration](configuration.md) | [Troubleshooting](troubleshooting.md)

## Separate a track

1. Start the stack using the [quickstart](../README.md#quickstart) and open http://localhost:3000.
2. Select audio with the file picker. Supported extensions are MP3, WAV, FLAC, OGG, M4A, and AAC. Keep uploads below 100 MiB to leave room for multipart overhead at the web proxy.
3. Choose **All 6 Stems / All 4 Stems** or **Isolate One**, then select the format and model.
4. Click **Upload & Process** and watch the status and elapsed time.
5. When completed, download each stem from the current job or **Recent Jobs**.

Output filenames include the sanitized original track name and stem, such as `song_t2s_vocals.mp3`.

## Models and stems

| Model | Available stems |
|-------|-----------------|
| `htdemucs_6s` (default) | Vocals, drums, bass, guitar, piano, other |
| `htdemucs`, `htdemucs_ft`, `hdemucs_mmi`, `mdx`, `mdx_extra`, `mdx_q`, `mdx_extra_q` | Vocals, drums, bass, other |

Guitar and piano isolation require `htdemucs_6s`. In isolate mode, vocals produce `vocals` and `instrumental`; another instrument produces that stem and `backing`.

Isolate mode still separates the full track before FFmpeg mixes the remaining stems. It is not a faster two-stem inference path. The API also accepts `other` as an isolated stem, though the browser's selector does not offer it.

## Output formats

| Format | Behavior |
|--------|----------|
| MP3 (default) | Demucs outputs 320 kbps MP3; backing mixes also request 320 kbps |
| WAV | Demucs produces WAV without a later FLAC conversion |
| FLAC | Demucs produces intermediate WAV files, then FFmpeg converts the selected outputs to FLAC |

## Advanced tuning

The **Advanced Tuning** panel exposes these options. The processor validates the listed values, but Demucs may reject settings that are incompatible with the chosen model.

| Setting | Browser default | Accepted values |
|---------|-----------------|-----------------|
| Segment size | Default (no override) | No override, or 8, 10, 15, 20, 25, 30, 40, 60 seconds |
| Overlap | `0.25` | No override, or `0.1`, `0.15`, `0.2`, `0.25`, `0.3`, `0.35`, `0.4`, `0.5` |
| Shifts | `0` | API accepts integers 0 through 10; the browser offers 0, 1, 2, 5, 10 |
| Clip mode | `rescale` | `rescale` or `clamp` |

Leave segment size at **Default** initially. Larger overlap, additional shifts, and fine-tuned models can increase processing time.

The processor adds Demucs's `--shifts` argument only for positive values; `0` leaves the upstream CLI default in effect. Do not treat the browser's "off" label as a guarantee that Demucs shift augmentation is disabled.

## Progress, previews, and history

The browser polls job status and processor progress every two seconds. Progress combines parsed Demucs output and time-based estimation, so it is not an accurate remaining-time forecast.

The component named `Spectrogram` draws amplitude waveforms, not frequency spectrograms. Browser audio decoding support determines which formats can be previewed; a failed waveform does not necessarily mean the processor cannot read the file.

Recent-job metadata, the current job, and its timer are saved in browser localStorage for refresh recovery. The backend job map is separate and only lives in memory. See [data lifecycle](configuration.md#limitations-and-data-lifecycle) before restarting services or relying on old downloads.

The API supports cancellation through job deletion. This is [best-effort](configuration.md#limitations-and-data-lifecycle), not a guarantee that all processing stages stop immediately.
