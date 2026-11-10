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

The shared local engine implements bounded CPU segment workers with normalized overlap-add, cancellation checks, and one cached model. See [advanced tuning](usage.md#advanced-tuning) for memory/quality tradeoffs. Distributed workers, a durable queue and GPU execution remain future work.

Discuss proposals through [repository issues](https://github.com/mbianchidev/track2stem/issues) before implementing a substantial change.
