# ADR 0005: SLO and Alerting Strategy

- Status: Accepted
- Date: 2026-05-05
- Deciders: Topic Compaction MI maintainers

## Context

Phase 5 shipped a baseline `PrometheusRule` with six symptom-based
alerts. For V1.0 we want a more disciplined approach: a clear set
of SLOs that the on-call team can be paged against, plus symptom
alerts for things that don't fit the SLO model (pod absence, disk
fill).

## Decision

### SLI and SLO definitions

| SLO | Definition | Target | Window |
|---|---|---|---|
| Compaction success rate | upserts / (upserts + non-loop skips) | >= 99% | 5m rolling |
| Lookup latency p95 | http_server_requests_seconds p95 on `/api/v1/kv` | < 50ms | 5m rolling |
| Lookup miss ratio | misses / total lookups | < 5% | 5m rolling |

The SLIs are computed by recording rules in the
`topic-compaction.recording` group of `81-prometheusrule.yaml`,
prefix-named `topic_compaction:` per the
common-recording-rule-naming convention. Recording rules give us:

- A single source of truth for dashboards and alerts.
- Cheap querying (the rule evaluates once per scrape, dashboards
  read the pre-computed series).
- A clean history of the SLI value over time.

### Alert taxonomy

Three groups in the `PrometheusRule`:

1. **Symptom alerts** (`topic-compaction.symptom-alerts`): page the
   on-call when the user is in immediate pain. Pod absence,
   readiness failure, memory pressure.
2. **SLO alerts** (`topic-compaction.slo-alerts`): page when a
   well-defined SLI breaches its target. Compaction success rate,
   lookup latency, lookup miss ratio.
3. **Capacity alerts** (`topic-compaction.capacity-alerts`):
   notify (not page) when something is off but not yet broken.
   KV growth, PVC fill.

### Severity policy

| Severity | Page? | Examples |
|---|---|---|
| `critical` | yes (on-call) | Pod absent, pod NotReady |
| `warning` | no (ticket) | SLO breach, capacity alerts |

Capacity and SLO alerts are not pageable in V1.0. Once the team
has SLO error budgets defined in a separate budget-tracking system,
SLO alerts can be promoted to page on burn-rate.

### Multi-window burn-rate alerting

Deferred. The full pattern (1h fast burn + 6h slow burn) needs an
explicit error budget which we have not committed to in V1.0. The
single-window 5-minute SLO alerts give us a useful signal without
the operational overhead of error-budget tracking.

When error budgets are introduced, the burn-rate alerts will:

- Replace the per-window SLO alerts.
- Use multi-window selectors (e.g. fast burn over 5m AND 1h, slow
  burn over 30m AND 6h).
- Be pageable for fast-burn, ticket-only for slow-burn.

### Runbook policy

Every alert MUST carry a `runbook` label whose value matches a
section in `docs/OPERATIONS.md`. The runbook section MUST include:

- "What it means" - what condition has Prometheus observed.
- "Verify" - commands or queries to confirm the alert.
- "Common causes and recovery" - prioritised by frequency.

Alerts without a runbook section fail review.

### Recording rule naming

`<service>:<sli>:<window>` per the Prometheus naming convention,
e.g. `topic_compaction:compaction_success_rate:5m`. Window is part
of the metric name so the same SLI computed over different windows
is unambiguous.

## Consequences

### Positive

- Dashboards and alerts share the recording rules, eliminating
  drift.
- Clear separation between "the user is in pain" and "we're
  trending toward pain".
- Runbooks are enforced by convention.

### Negative / Trade-offs

- Single-window SLO alerts are noisier than multi-window
  burn-rate alerts. We accept this for V1.0; revisit with proper
  error budgets in a future iteration.
- Recording rules add Prometheus storage cost (one new series per
  rule, evaluated every 30s). For three rules at 30s this is
  negligible.

## Alternatives Considered

- **No SLOs, just symptom alerts**: rejected because the on-call
  team cannot reason about service quality from raw counters.
- **Multi-window burn-rate from day one**: rejected because we
  don't have explicit error budgets yet, so the burn rate has no
  reference.
- **Per-pod alerts**: rejected; the V1.0 deployment is single-pod
  per ADR 0002, so per-pod alerts add no information.

## References

- `81-prometheusrule.yaml` - the actual rules
- `82-grafana-dashboard.yaml` - dashboard consuming the recording
  rules
- `docs/OPERATIONS.md` - runbook
- The Site Reliability Workbook chapter on alerting (Google) for
  the multi-window burn-rate pattern that V2 should adopt
