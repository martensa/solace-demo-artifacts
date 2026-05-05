# Performance

This document records the V1.0 performance baseline of the Topic
Compaction MI -- expected throughput, latency, and resource use --
plus the harness used to measure it.

The numbers below come from the lab environment (Rancher Desktop on
Apple Silicon, Solace Cloud Standard service in `eu-west-1`). Treat
them as a sanity-check baseline, not as a production capacity
guarantee.

## Expected SLOs

| SLO | Target |
|---|---|
| Compaction success rate | >= 99% |
| Lookup p95 latency | < 50ms |
| Lookup miss ratio | < 5% |

See `docs/adr/0005-slo-and-alert-strategy.md` for the rationale.

## V1.0 baseline

Sustained workload, single MI replica with the default resource
limits (200m / 512Mi requests, 1000m / 1Gi limits):

| Metric | Observed | Notes |
|---|---|---|
| Compaction throughput | 100 msg/s sustainable | Limited primarily by the bash-driven REST harness, not the MI |
| Lookup throughput | 200 req/s sustainable | Single replica, single connection; HTTP keep-alive helps |
| Lookup p50 / p95 / p99 | ~3 / ~12 / ~25 ms | Cold cache; warm cache halves these |
| RocksDB write amp | ~1.5x | Stable under steady-state |
| Pod CPU steady-state | ~80m | Idle; bursts to 200-300m during compaction or bulk-replay |
| Pod memory | ~280 MiB | Stable; mostly off-heap RocksDB block cache |
| KV size on disk | ~1.0 KB / record | Median-sized order-event payloads |

The `examples/load-test.sh` harness was used to drive these
numbers. See "Load test harness" below.

## Bulk replay

`BULK_REPLAY` is rate-limited (`options.rateLimit`, default 1000
msg/s). Observed at the lab broker:

| Pattern | Matches | Configured rate | Observed | Wall-clock |
|---|---|---|---|---|
| `orders/created/*` | 100 | 100 msg/s | 100/s | ~1.0s |
| `orders/created/*` | 1000 | 500 msg/s | 500/s | ~2.0s |
| `orders/>` | 10000 | 1000 msg/s | 1000/s | ~10s |

The rate limiter (Bucket4j) is the dominant factor; raise it for
tighter recovery windows, but watch the broker queue backlog.

## Load test harness

`examples/load-test.sh` drives configurable producer load via the
broker REST endpoint and samples the MI's Prometheus metrics. It
is intentionally simple (bash + curl) so it runs on any laptop;
production benchmarking should switch to sdkperf with the JCSMP
client for honest throughput numbers above ~500 msg/s.

```bash
# Default: 100 msg/s for 30s with 100 unique keys
./examples/load-test.sh

# Override
./examples/load-test.sh --rate 500 --duration 60 --keys 1000

# Custom topic prefix (must match the compaction.data
# subscription pattern)
./examples/load-test.sh --prefix orders/bench
```

Output: per-second progress with target rate, observed compaction
rate, and a final summary table including KV size and lookup p95.

## Capacity planning

| Resource | Sizing rule of thumb |
|---|---|
| RocksDB on disk | ~1 KB per record on average; size the PVC at 2x your expected unique-key cardinality |
| Memory | 512 MiB per million records is safe; tune RocksDB block cache for read-heavy workloads |
| CPU | 200m steady-state; bursts to 1 core during compaction or bulk-replay |
| Network egress | Dominated by Solace SMF; size for peak producer rate * payload size |

## Known performance limits

- **Single-replica deployment** (ADR 0002): max throughput is
  bounded by one pod. V2 HA will allow horizontal scaling for
  read traffic only (compaction stays single-leader).
- **Bash-based load test**: tops out around 200 msg/s on commodity
  hardware due to curl process spawning. Use sdkperf for higher
  rates.
- **RocksDB compaction stalls**: under heavy continuous writes
  the foreground write rate can drop briefly while RocksDB
  compacts SST files. Monitor `container_fs_writes_bytes_total`
  and the `topic_compaction:lookup_p95_seconds:5m` SLO; if
  breaches correlate, tune the RocksDB level thresholds.

## Future work

- **Testcontainers-based integration tests** that drive a real
  Solace broker via JCSMP, deferred from V1.0 (the
  `@SpringBootTest` setup conflicts with the MI Framework's
  auto-configuration; needs a slimmer test slice or a dedicated
  test profile). Tracked for V1.1.
- **sdkperf wrapper** for high-throughput benchmarking; the
  current bash harness is fine for sanity but not for sustained
  > 500 msg/s.
- **Per-workflow latency histograms** so the dashboard panel can
  show compaction / replay / lookup latencies separately rather
  than via the generic `http_server_requests_seconds_bucket`
  series.
- **Soak test** at 100% CPU and 90% memory for 24h to flush out
  resource leaks, especially around RocksDB block cache.
