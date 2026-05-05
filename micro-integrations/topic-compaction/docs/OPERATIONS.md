# Operations

This document is the on-call runbook for the Topic Compaction MI in
production-shaped deployments. It covers everyday tasks, alert
responses, and disaster recovery.

## Quick reference

```bash
# Where it runs
NAMESPACE=mi-solace-lab

# Most common operations from the make wrapper
make k8s-status           # pods, svc, pvc, monitoring
make k8s-logs             # tail JSON logs
make k8s-port-forward     # 18090 -> service:8090
make k8s-restart          # rollout restart
make k8s-deploy           # idempotent re-deploy
make k8s-undeploy         # tear down (keeps PVC)
make k8s-undeploy-purge   # full teardown (deletes PVC + namespace)

# Direct kubectl
kubectl -n mi-solace-lab get pod,svc,pvc,pdb,networkpolicy
kubectl -n mi-solace-lab logs -f \
    -l app.kubernetes.io/name=topic-compaction-mi
kubectl -n mi-solace-lab describe pod \
    -l app.kubernetes.io/name=topic-compaction-mi
```

## SLOs

| SLO | Target | Window | Alert |
|---|---|---|---|
| Compaction success rate | >= 99% | 5m | TopicCompactionSuccessRateBelowSlo |
| Lookup latency p95 | < 50ms | 5m | TopicCompactionLookupP95SloBreach |
| Lookup miss ratio | < 5% | 5m | TopicCompactionLookupMissRateHigh |

Recording rules computing these SLIs live in
`81-prometheusrule.yaml` under the `topic-compaction.recording`
group. The Grafana dashboard ("Topic Compaction MI") shows them in
the top stat row.

## Alert response

### TopicCompactionMiAbsent (CRITICAL)

What it means: Prometheus has not had a successful scrape for 2
minutes. The pod is most likely down or in `CrashLoopBackoff`.

Verify:

```bash
kubectl -n mi-solace-lab get pod \
    -l app.kubernetes.io/name=topic-compaction-mi
kubectl -n mi-solace-lab describe pod \
    -l app.kubernetes.io/name=topic-compaction-mi
```

Common causes and recovery:

- Image pull error -> verify the registry credential secret
  (`registry-solace-lab-pull`) is present in `mi-solace-lab` and
  not expired.
- OOMKill -> check `kubectl describe` for `OOMKilled` reason; bump
  `resources.limits.memory` in `40-deployment.yaml` and re-deploy.
- Solace broker unreachable -> verify the `SOLACE_HOST` in the
  Secret resolves and the egress NetworkPolicy allows traffic.
- ConfigMap typo -> check pod events for `MountVolume` errors.

### TopicCompactionMiPodNotReady (CRITICAL)

What it means: the pod is running but the readiness probe has
failed for 5 minutes. Traffic is not being routed to it.

The readiness group includes the Solace binders. Most often this
fires because the binders cannot reach the broker.

Verify:

```bash
curl -s http://<pod-ip>:8090/actuator/health/readiness | jq .
```

Look at the `binders.solace.connection.status` and per-input
status. Recovery steps depend on which sub-component is DOWN:

- All bindings DOWN -> broker connection error. Check the SMF
  port (55555 or 55443/TLS). Verify the credential secret.
- Single binding DOWN -> queue does not exist on the broker.
  Either provision manually (Solace Cloud UI) or enable
  `topic-compaction.provisioning.enabled` and supply admin SEMP
  creds in the Secret.

### TopicCompactionSuccessRateBelowSlo (WARNING)

What it means: more than 1% of inbound messages are being skipped
for non-loop reasons over a 10-minute window.

Investigate:

```promql
sum by (reason) (
  rate(topic_compaction_skipped_total{
    application="topic-compaction-mi"}[5m])
)
```

Reasons:

- `out_of_order` -> producers are publishing with a
  `senderTimestamp` header that goes backwards. Check producer
  clocks; consider disabling ordering by setting
  `topic-compaction.compaction.ordering.header` to empty.
- `no_topic` -> the inbound message is missing
  `solace_destination`. Likely a custom binder or an SMF client
  publishing without the Solace destination header. The message
  is unidentifiable; investigate the producer side.
- `loop` -> these are expected and are excluded from the SLO.

### TopicCompactionLookupP95SloBreach (WARNING)

What it means: lookup p95 latency > 50ms over 10 minutes.

Likely causes:

- RocksDB compacting -> check `container_fs_writes_bytes_total`
  for the pod; expect a spike. Wait it out, or tune RocksDB level
  thresholds for less frequent compaction.
- PVC IOPS saturation -> check the storage class. Default
  `local-path` provisioner shares the node disk; under heavy IO
  it slows down. Move to a dedicated SSD-backed StorageClass for
  production.
- KV size too large -> check `topic_compaction_kvstore_size`.
  Enable retention if not already on (see "Enabling retention"
  below).

### TopicCompactionLookupMissRateHigh (WARNING)

What it means: > 5% of lookups return "not found" over 15 minutes
(while traffic is meaningful, > 0.1 lookups/s).

Likely causes:

- Producer publishes on a topic outside the
  `compaction.data` queue's subscription pattern. Verify the
  subscription matches the producer pattern.
- Lookup client is using the wrong key encoding. Check the
  `x-compaction-key` header or the topic-key prefix in the
  request.
- Retention sweeper is too aggressive. Check
  `topic_compaction_retention_evicted_total`.

### TopicCompactionPodMemoryHigh (WARNING)

What it means: working-set memory > 90% of limit for 10 minutes.

Recovery:

- Bump `resources.limits.memory` in the Deployment.
- Tune RocksDB block-cache size via env var
  `ROCKSDB_BLOCK_CACHE_SIZE` (defaults to JVM-managed off-heap;
  V1.0 does not yet expose this knob -- a future iteration will).
- Restart the pod to clear off-heap fragmentation (`make
  k8s-restart`).

### TopicCompactionKvStoreSizeGrowth (WARNING)

What it means: KV store grew by > 100k records in the last hour.

Investigate:

- Is a producer in a loop? Check
  `topic_compaction_skipped_total{reason="loop"}` -- if it's
  growing fast, loop protection IS firing but the producer is
  still hammering.
- Is the topic cardinality genuinely high? Check
  `kubelet_volume_stats_used_bytes` for the PVC; if it crosses
  85% the `TopicCompactionDiskUsageHigh` alert will follow.

### TopicCompactionDiskUsageHigh (WARNING)

What it means: PVC > 85% full.

Recovery:

- Enable retention with a tighter default-TTL.
- Run a cascade DELETE for known-stale prefixes via the command
  event API.
- Increase the PVC size: edit `30-pvc.yaml` and re-apply (the
  underlying StorageClass must support resize).

## Common operational tasks

### Routine restart

```bash
make k8s-restart
```

State persists across restart because RocksDB is on the PVC. The
graceful-shutdown contract (server.shutdown=graceful + RocksDB WAL
sync in @PreDestroy) ensures no in-flight messages are lost.

### Rotating REST credentials

Update the Secret and bounce the pod:

```bash
$EDITOR .env       # change MI_USER_PASSWORD / MI_ADMIN_PASSWORD
make k8s-deploy    # re-renders + applies the Secret
make k8s-restart   # picks up new env values
```

### Enabling retention

Edit `10-configmap.yaml`, set:

```yaml
topic-compaction:
  retention:
    enabled: true
    check-interval: PT5M
    default-ttl: PT24H
    rules:
      - prefix: "orders/"
        ttl: PT7D
      - prefix: "ephemeral/"
        ttl: PT1H
```

Then `make k8s-deploy` -- the config-checksum annotation triggers a
rollout that picks up the new ConfigMap.

### Manual backup / restore

Use the admin REST endpoints. Backup is a streaming line-delimited
JSON.

```bash
make k8s-port-forward
# in another terminal:
curl -s -u "$MI_ADMIN_NAME:$MI_ADMIN_PASSWORD" \
    -X POST http://localhost:18090/api/v1/admin/backup \
    -o backup-$(date +%Y%m%d-%H%M%S).ndjson

curl -s -u "$MI_ADMIN_NAME:$MI_ADMIN_PASSWORD" \
    -X POST http://localhost:18090/api/v1/admin/restore \
    -H 'Content-Type: application/x-ndjson' \
    --data-binary @backup-...ndjson
```

For production restores, isolate the MI from inbound traffic
first (cordon the namespace via NetworkPolicy or scale to 0
producers).

### Triggering a one-off bulk replay

Send a command event to the broker:

```bash
curl -X POST -u "$SOLACE_REST_USER:$SOLACE_REST_PASS" \
    "$SOLACE_REST_HOST/TOPIC/compacted/command/bulk-replay" \
    -H 'Content-Type: application/json' \
    -d '{"command":"BULK_REPLAY","pattern":"orders/created/>",
         "options":{"correlationId":"manual-2026-05-05",
                    "rateLimit":500}}'
```

Subscribe to `topic-compaction/replay/bulk-result` to observe the
summary event when the iteration completes.

## Disaster recovery

### Pod is permanently OOMKilled

Increase memory limit, or resize the JVM heap downwards (the
Spring Boot starter sets it via container memory by default).

```bash
kubectl -n mi-solace-lab edit deployment topic-compaction-mi
# adjust resources.limits.memory, save, exit
```

The Deployment uses `strategy: Recreate`, so the pod restarts
once the previous one is fully gone.

### RocksDB corruption

Symptom: pod fails to open RocksDB on startup with a
`STATUS_CORRUPTION` exception in the logs.

Recovery:

1. Take a backup attempt of the PVC (might fail; that's fine).
2. Delete the Deployment but KEEP the PVC.
3. Spawn a debug pod that mounts the PVC, copy what is salvageable.
4. `make k8s-undeploy --delete-data` (destroys the PVC), then
   `make k8s-deploy` (creates a fresh PVC).
5. Reload state from the most recent backup via
   `POST /api/v1/admin/restore`.

### Cluster-wide outage

V1.0 has no HA (ADR 0002). The MI is back as soon as the cluster
recovers and Solace re-delivers any in-flight messages from the
queues. RocksDB state survives across the outage because the PVC
is persistent.

## Capacity planning

| Metric | Sizing rule |
|---|---|
| RocksDB KV size | ~1 KB per record on average; budget the PVC at 2x your expected unique key cardinality |
| Memory | 512 MiB per million records is a safe starting point; tune RocksDB block cache for read-heavy workloads |
| CPU | 200m for steady-state; bursts during compaction or bulk-replay can hit 1 core |
| Network egress | dominated by Solace SMF; size for peak producer rate * payload size |

## Related documents

- `docs/ARCHITECTURE.md` -- architectural baseline
- `docs/OBSERVABILITY.md` -- metrics, logs, traces reference
- `docs/SECURITY.md` -- authn/authz, secret handling (Phase 8)
- `docs/COMMAND-EVENTS.md` -- replay/delete command schema
- `docs/adr/0001-architecture.md` -- ADR baseline
- `docs/adr/0002-no-ha-in-v1.md` -- HA deferral
- `docs/adr/0003-k8s-deployment.md` -- K8s topology
- `docs/adr/0004-rest-auth-roles.md` -- REST role model
- `docs/adr/0005-slo-and-alert-strategy.md` -- SLO + alert design
