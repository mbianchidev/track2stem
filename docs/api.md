# API reference

[Documentation index](README.md) | [Usage](usage.md) | [Configuration](configuration.md)

Use `http://localhost:8080/api` directly or `/api` through the frontend's Nginx proxy. The API has no authentication and is intended for trusted local use.

## Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/upload` | Submit an audio file as multipart form data |
| `GET` | `/api/jobs` | List jobs currently known to the backend |
| `GET` | `/api/jobs/{id}` | Get job status and output metadata |
| `DELETE` | `/api/jobs/{id}` | Request cancellation if active, then remove the backend job record |
| `GET` | `/api/download/{id}/{stem}` | Download a completed job's stem |
| `GET` | `/api/processing-status/{id}` | Get processor progress via the backend |
| `GET` | `/api/health` | Return `{"status":"ok"}` |

## Upload options

| Multipart field | Default | Accepted values |
|-----------------|---------|-----------------|
| `file` | Required | Audio file with a supported extension |
| `output_format` | `mp3` | `mp3`, `wav`, `flac` |
| `model` | `htdemucs_6s` | The eight [supported models](usage.md#models-and-stems) |
| `stem_mode` | `all` | `all`, `isolate` |
| `isolate_stem` | `vocals` | `vocals`, `drums`, `bass`, `guitar`, `piano`, `other`; guitar/piano require `htdemucs_6s` |
| `segment` | No override | Values in [advanced tuning](usage.md#advanced-tuning) |
| `overlap` | No override | Values in [advanced tuning](usage.md#advanced-tuning); the browser sends `0.25` by default |
| `shifts` | `0` | Integers 0 through 10; see the [upstream-default caveat](usage.md#advanced-tuning) |
| `clip_mode` | `rescale` | `rescale`, `clamp` |

The processor validates numeric options and model/stem compatibility. A backend upload can return a job record before a later processor validation failure, which then appears in the job's `error`.

## Examples

Upload with defaults (all six stems, MP3):

```bash
curl --fail -F "file=@song.mp3" http://localhost:8080/api/upload
```

Request vocals and instrumental backing in FLAC:

```bash
curl --fail http://localhost:8080/api/upload \
  -F "file=@song.mp3" \
  -F "output_format=flac" \
  -F "model=htdemucs_6s" \
  -F "stem_mode=isolate" \
  -F "isolate_stem=vocals"
```

Copy the returned `id` into the following commands:

```bash
JOB_ID='replace-with-the-id-from-the-upload-response'

curl --fail "http://localhost:8080/api/jobs/$JOB_ID"
curl --fail "http://localhost:8080/api/processing-status/$JOB_ID"

# Run after the job reaches "completed".
curl --fail --remote-name --remote-header-name \
  "http://localhost:8080/api/download/$JOB_ID/vocals"

# Requests cancellation if active and removes the backend job record.
curl --fail -X DELETE "http://localhost:8080/api/jobs/$JOB_ID"
```

## Job lifecycle

Statuses are `pending`, `processing`, `completed`, or `failed`. Completed records include `processing_time` and an `output_files` map keyed by stem name. Its values are internal filesystem paths, not public URLs; download through the job/stem endpoint.

The backend stores jobs in memory only. Deletion returns `{"status":"deleted"}` but is not a disk-cleanup operation. Restart and retention behavior are described in [data lifecycle](configuration.md#limitations-and-data-lifecycle).

Progress responses are separate from job records. The backend can return an `unknown` progress state when the processor is unavailable; check the job endpoint for its final status or error.
