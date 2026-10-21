# Roadmap

[Documentation index](README.md) | [Implemented features](../README.md#features)

These are future directions, **not implemented features or delivery commitments**:

- Durable job persistence with PostgreSQL and Valkey.
- User authentication and rate limiting.
- A managed RabbitMQ worker queue.
- Automatic file expiration and cleanup.
- OpenTelemetry/Prometheus/Grafana observability.
- SeaweedFS object storage.

## Parallel separation

Application-level segment splitting and parallel workers are a possible future optimization, not a current feature. A design would need to address boundary artifacts, crossfades or overlap-add, additional memory use, CPU contention, cancellation, and reassembly before it could be enabled safely.

Discuss proposals through [repository issues](https://github.com/mbianchidev/track2stem/issues) before implementing a substantial change.
