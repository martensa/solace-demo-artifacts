# ADR 0002: No High Availability in V1.0

- Status: Accepted
- Date: 2026-05-05
- Deciders: Topic Compaction MI maintainers
- Supersedes: none

## Context

A production deployment of an event-streaming component typically
expects high availability: at least active-standby with fast failover,
ideally with replicated state to avoid data loss on pod failure.

The Topic Compaction MI's state is held in RocksDB, local to the pod.
Achieving HA requires one of:

1. Active-standby with leader election and a synchronously replicated
   state store (e.g. RocksDB shipping its WAL to a sibling, or a shared
   blob store).
2. Active-active with an external transactional KV store (e.g. Redis
   with persistence) replacing the embedded RocksDB.
3. Cold-standby with periodic snapshots and a manual restore procedure.

Option 1 is the canonical choice for low-latency event-streaming and is
what the Solace MI Framework's leader-election feature is designed for.
However it requires a non-trivial state-replication implementation that
RocksDB does not give us out of the box. A correct implementation needs:

- A leader-election mechanism (the MI Framework provides this).
- A state-shipping layer (custom, not provided by the framework).
- A failover protocol that drains in-flight Solace ACKs cleanly so the
  new leader does not double-process or drop messages.
- Comprehensive tests covering split-brain, partial failure, and
  rollback scenarios.

Option 2 changes the architectural baseline (ADR 0001) and removes one
of the differentiators (immediate, in-process compaction with O(1)
lookup against local memory/disk).

Option 3 is operationally weak - it accepts data loss between snapshots.

## Decision

V1.0 ships with **single-replica deployment** and **no HA**. We accept:

- A pod failure pauses replay/lookup until the K8s scheduler restarts
  the pod.
- In-flight Solace messages on the workflow queues are redelivered to
  the new pod once it comes up; Solace's persistent queue semantics
  cover the messaging layer.
- Recovery time objective (RTO) is bounded by the K8s restart policy,
  the readiness probe, and RocksDB-WAL-replay. Empirically: under one
  minute for a healthy cluster.
- Recovery point objective (RPO) is zero for messages that have been
  acked by the MI prior to the failure (RocksDB WAL is fsync'd before
  ack), bounded by the queue depth otherwise.

Backup/restore tooling (introduced in a later ADR) and a
PodDisruptionBudget for graceful drains are the v1.x mitigations.

## Consequences

### Positive

- Architectural simplicity: one process owns the state, no
  state-replication code path.
- Faster path to a release-able V1.0.
- Operations can be reasoned about with standard K8s primitives:
  liveness/readiness probes, PVC, restart policy, PDB.

### Negative

- A pod failure causes a brief outage of replay and lookup workflows.
  Compaction continues to be served by Solace's persistent queue
  (messages await the next leader).
- Single-PVC failure is a single point of state loss. Mitigated by
  scheduled backups (later ADR), not eliminated.
- HA is the most common follow-up question from operators reviewing the
  MI. We document this trade-off prominently in `README.md` and
  `docs/OPERATIONS.md`.

## Plan for V2

When V2 starts, the canonical approach is:

1. Keep RocksDB local; add a state-replication module that ships the
   WAL (or RocksDB checkpoints) to a sibling.
2. Use the MI Framework leader-election to elect a primary; followers
   apply the shipped WAL and stay warm.
3. On failover, the new leader replays its WAL tail before switching
   bindings to active and resuming traffic.
4. Add chaos tests covering split-brain and disk-corruption scenarios.

Estimated effort: two to three engineer-weeks for a robust
implementation, plus a comparable test investment.

## Alternatives Considered

See "Context" above. The alternatives were rejected for the reasons
stated there.

## References

- ADR 0001: Baseline architecture.
- `docs/OPERATIONS.md` (added in Phase 6) for the runbook describing
  the v1.x failure modes and recovery steps.
