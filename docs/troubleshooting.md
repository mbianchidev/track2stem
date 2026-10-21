# Troubleshooting

[Documentation index](README.md) | [Configuration and limitations](configuration.md)

Inspect status and recent logs from the repository root:

```bash
docker compose ps
docker compose logs --tail=100 backend processor
```

| Symptom | What to check |
|---------|---------------|
| Containers fail to start or become healthy | Confirm the runtime is running (`docker info`), ports 3000/8080 are free, and the build completed. Review logs before increasing the startup wait timeout. |
| First job is slow | Check processor logs for model downloads and internet access. Healthy containers do not mean a model is cached. |
| Processing fails or runs out of memory | Try a shorter input, allocate more memory to the runtime, and leave segment size at Default to avoid model-specific incompatibilities. |
| Processing times out | Both the backend processor request and Demucs separation have 30-minute limits. Use a shorter source or a less expensive model/settings combination. |
| Upload is rejected | Check the extension, request size, free disk space, and backend logs. Nginx's 100 MiB limit includes multipart overhead. |
| Waveform preview fails | The browser may not decode a format that the processor supports. Try WAV or MP3. |
| Separation quality is poor | Start from a high-quality source and try another model in the UI. AI separation can leave artifacts or bleed between stems. |
| Old jobs are visible but downloads fail after restart | Browser metadata survived, but the backend's in-memory job map did not. Download needed results before restarting the backend. |
| A `.env` edit has no effect | The supplied Compose file does not interpolate its example environment file. See [configuration](configuration.md#service-configuration). |

To rebuild after changing an image or its dependencies, run `docker compose build --no-cache`, then recreate the affected services. Recreating the processor can discard its model cache, and restarting the backend loses its job records.

If the problem persists, search [existing issues](https://github.com/mbianchidev/track2stem/issues) before reporting a reproducible bug. Include platform/runtime versions, selected model and options, error messages, and sanitized logs. Do not attach private audio or credentials.
