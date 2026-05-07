# Changelog

All notable changes to the Topic Compaction Micro-Integration are
documented in this file.

The format is based on [Keep a Changelog][kac], and this project adheres
to [Semantic Versioning][semver].

[kac]: https://keepachangelog.com/en/1.1.0/
[semver]: https://semver.org/spec/v2.0.0.html

## [1.2.0] - 2026-05-07

End-to-end W3C trace context propagation across Solace messages.
Closes the gap on V1.1.x's internal-only tracing: every span the
MI emits now links to its upstream publisher's trace and stamps its
trace ids onto its own outbound publishes so downstream subscribers
continue the trace.

### Added

- {observability.SolaceContextPropagation}: Spring component that
  wraps Micrometer Tracing's {Tracer} + {Propagator} so the MI's
  consumer / publisher hot paths can speak the W3C trace-context
  protocol against Solace user properties. Three carrier shapes
  cover all MI traffic patterns:
  - {Propagator.Getter<Message<?>>} reads trace headers from
    inbound Spring Messages (Solace user properties surface as
    headers via the Solace binder's
    {SmfMessageHeaderWriteCompatibility}).
  - {Propagator.Setter<SDTMap>} writes trace headers onto outbound
    JCSMP user properties for the {DirectAuditPublisher}'s
    DELIVERY-DIRECT path.
  - {Propagator.Setter<Map<String,String>>} for snapshotting the
    current context as a header bag suitable for Spring Message
    builders, used by StreamBridge call sites where the binder
    forwards Spring headers into Solace user properties.
  Convenience methods:
  - {extractAndStart(Message, workflowName)} returns an
    {InboundScope} (try-with-resources) which extracts the
    upstream context, starts a CONSUMER-kind receive span via
    {Tracer.withSpan}, and ends both on close.
  - {injectInto(SDTMap)} stamps the current trace context onto a
    JCSMP user-property map.
  - {currentContextAsHeaders()} returns a {Map} ready to forward
    into a {MessageBuilder.setHeader} loop.

  Why Micrometer rather than raw OpenTelemetry: the {@Observed}
  annotations resolve their parent via Micrometer's
  {ObservationRegistry} thread-local. Activating an OTel
  {Context.makeCurrent()} alone does not update Micrometer's
  thread-local, so {@Observed} spans become trace roots even when
  an OTel context is active. The OTel-bridge keeps the two
  thread-locals in sync only when entering via Micrometer's
  {Tracer.withSpan}. Routing through Micrometer guarantees the
  upstream context is the parent of every {@Observed} span.

### Changed

- All three consumer interceptors
  ({CompactionConsumerInterceptor},
  {CommandConsumerInterceptor},
  {LookupConsumerInterceptor}) now wrap their work in a try-with-
  resources block over {SolaceContextPropagation.extractAndStart}.
  Resulting per-inbound span tree:

  ```
  upstream publisher span        (extracted from traceparent)
  └─ <workflow>.inbound          (CONSUMER, started by helper)
     └─ <@Observed work span>    (compact-message etc.)
        └─ ... nested spans
  ```

  When the inbound has no {traceparent} header (uninstrumented
  publisher), the receive span becomes a trace root and behaviour
  is unchanged from V1.1.x.

- {DirectAuditPublisher}'s three publish methods
  ({publishAudit}, {publishJsonDirect},
  {publishDirectBytes}) now always allocate the
  {SDTMap} user-property carrier and call
  {SolaceContextPropagation.injectInto} before
  {producer.send}. Audits / summaries / lookup replies carry
  W3C trace headers regardless of whether other user properties
  are set.

- {BulkReplayService.buildReplayMessage} and
  {CommandConsumerInterceptor.handleSingleReplay} stamp
  {currentContextAsHeaders()} onto the Spring Message before the
  StreamBridge call. The Solace binder copies these headers into
  Solace user properties on send.

### Test infrastructure

- New {SolaceContextPropagationTest} (6 cases) using
  {Tracer.NOOP} + {Propagator.NOOP} to verify the helper's
  defensive contract: never throws on null carriers, returns
  empty when no span is active, hands back a usable
  {InboundScope}, idempotent close. Realistic
  inject/extract behaviour against a running broker is verified
  end-to-end live.

- Existing tests for {BulkReplayService},
  {DirectAuditPublisher}, {ReplayProducerInterceptor} and
  {EndToEndIntegrationTest} updated to pass {Tracer.NOOP} +
  {Propagator.NOOP} as the new {SolaceContextPropagation}
  constructor argument.

Total test count: 122 (was 116) + 3 Testcontainers integration
tests, JaCoCo coverage gate met.

### Lab verification

End-to-end propagation verified live: a REST publish to
{POST $SOLACE_REST_HOST/<topic>} with header
{Solace-User-Property-traceparent:
00-0011223344556677889900112233aabb-ccddeeff00112233-01}
produced a Jaeger trace under the synthesized
upstream traceID with two parent-child levels:
{compaction.inbound} -> {compact-message}, plus the audit
cascade as a sibling pair of receive + skipped-loop spans.

### Compatibility with Solace's official OTel stack

Solace publishes an OpenTelemetry Java Agent extension
({com.solace.spring.cloud:spring-cloud-stream-binder-solace-instrumentation}
+ {com.solace:solace-opentelemetry-jcsmp-integration}) that
instruments the Spring Cloud Stream Solace binder via byte-code
weaving when the OTel javaagent is attached at JVM startup. We
intentionally did **not** wire that path because:

1. Spring Boot 3.x with Micrometer Tracing already provides
   Spring-side auto-instrumentation; combining it with the OTel
   agent risks duplicate spans unless one is explicitly disabled.
2. The agent only instruments two pointcuts
   ({InboundXMLMessageListener.processMessage} and
   {MessageProducerSupport.sendMessage}), both already covered
   here: our {<workflow>.inbound} spans match the first; Spring
   Boot's auto-instrumentation of {StreamBridge} produces
   {stream-bridge process} spans matching the second.
3. The agent does not cover the two paths we genuinely need:
   {DirectAuditPublisher}'s direct JCSMP publishes outside the
   binder send path, and {StreamBridge} calls across thread
   boundaries.
4. The wire format is identical: the official Solace setter
   ({SolacePubSubPlusJavaTextMapSetter}) writes exactly the W3C
   standard header names ({traceparent}, {tracestate},
   {baggage}) to JCSMP user properties - the same names that
   {SolaceContextPropagation.injectInto(SDTMap)} writes via the
   Spring Boot-configured W3C propagator. Solace Cloud
   Distributed Tracing on the broker side accepts both
   identically.

For operators who prefer the agent-based "officially supported"
combination: disable Micrometer Tracing
({management.tracing.enabled: false}), package the agent JAR +
Solace extension JARs into the container image, set
{JAVA_OPTS=-javaagent:... -Dotel.javaagent.extensions=...}.
The MI's {SolaceContextPropagation} bean still works alongside
the agent (it's a pure no-op when no Micrometer span is active).

### Operator note: Solace PubSub+ Distributed Tracing

The MI's inject / extract is necessary but not sufficient for the
full end-to-end picture. To see broker-side hops
({BROKER_RECEIVE} / {BROKER_EGRESS} spans) in the same trace,
enable Solace PubSub+ Distributed Tracing on the broker:

- Solace Cloud: Cluster Manager -> Service -> "Distributed Tracing"
  tab -> create a Telemetry Profile pointing at the same OTLP
  collector the MI uses.
- Self-hosted broker: configure {tracing.span.batch}
  + {tracing.span.endpoint} via SEMP or CLI per the Solace
  PubSub+ Distributed Tracing reference.

The broker emits its own spans, parented onto the
{traceparent} the MI propagates, so the resulting trace tree in
Jaeger / Tempo shows publisher -> broker-receive -> broker-egress
-> MI consumer -> MI audit-publish -> broker-receive -> ...

Operators using SMF / JCSMP publishers from the application side
should ensure their publish path either uses the
{pubsubplus-opentelemetry-java-integration} library (PubSub+
Messaging API) or implements equivalent W3C header injection.
REST publishers can set {Solace-User-Property-traceparent: 00-...}
manually if their HTTP client has access to the active span.

## [1.1.4] - 2026-05-07

Bug fix on top of V1.1.3. Same architectural pattern, applied to
the LOOKUP workflow - the last remaining workflow that still
emitted via the binder publish path.

### Fixed

- **Lookup requests via Solace REST {@code /REQUESTS/...} timed
  out 100% of the time.** The lookup workflow's output binding
  (output-2) emits the response on the request's
  {@code solace_replyTo} destination, which for Solace REST
  request/reply is a temp queue with a DIRECT-only subscriber.
  The binder publishes PERSISTENT, the broker silently discards
  (no guaranteed endpoint), the publish-ack callback never fires,
  and the inbound consumer-ack on the lookup request hangs for
  the framework's {@code publish-timeout} window before the
  broker redelivers up to {@code maxRedeliveryCount=5}. Lab
  measurement: queue {@code ackedMsgCount=0}, every REST request
  returned {@code 504 Reply Wait Timeout}.

### Changed

- New {@code LookupConsumerInterceptorFactory} attached to
  {@code input-2}. Resolves the lookup synchronously, publishes
  the response via the V1.1.0 {@code DirectAuditPublisher} - new
  method {@code publishDirectBytes(topic, payload, contentType,
  userProperties, correlationId)} - with
  {@code DeliveryMode.DIRECT} matching the requestor's DIRECT
  subscription. Manually flushes the consumer-ack via
  {@code AckHelper}, returns null to suppress the workflow output.

- {@code LookupProducerInterceptorFactory} reduced to a pure
  suppressor. Returns {@code null} unconditionally so the binder
  output-2 path no longer fires.

- {@code DirectAuditPublisher.publishDirectBytes()}: new method.
  Generic fire-and-forget DIRECT publish with arbitrary bytes,
  optional content-type, optional user properties (Boolean /
  Integer / Long / String type-aware), and optional JCSMP
  correlation-id. Used by the lookup consumer interceptor to
  echo the requestor's correlation-id back on the reply.

### Operator note: OTEL Collector wiring

The K8s deployment now points at {http://host.docker.internal:4317}
by default to match the typical Rancher Desktop development setup
where an OTEL Collector runs on the host via docker-compose. The
{70-networkpolicy.yaml} grew an explicit egress rule for the Lima
VM gateway range ({192.168.5.0/24} on ports {4317} / {4318}) -
the previous Solace Cloud egress rule excluded all RFC1918 ranges,
which had silently blocked the trace export.

Switching to in-cluster Tempo or an external SaaS collector is a
single {kubectl set env OTEL_EXPORTER_OTLP_ENDPOINT=...} away;
{docs/OBSERVABILITY.md} has the full collector wiring matrix
(in-cluster, host docker-compose, external SaaS, gRPC vs HTTP
transport, sampling, vendor auth headers).

A pre-existing inaccuracy in {docs/OBSERVABILITY.md} was
corrected: span operation names in Jaeger / Tempo are the
{@Observed} {contextualName} attribute, not the {name}. The doc
now lists the correct mapping (e.g. {compact-message} for
{CompactionService.compact}).

### Operator note: Solace REST {@code /REQUESTS/...} is not reachable

Lab verification surfaced an architectural detail not visible from
the MI's source code: the Solace broker's REST gateway always
publishes the request side of {@code /REQUESTS/...} as a Direct
Message regardless of the {@code Solace-Delivery-Mode: persistent}
header. The MI's lookup workflow consumes from a durable queue
({@code compaction.lookup}), which only spools guaranteed traffic;
Direct messages on the matching topic pattern flow past the queue
without being captured. The lookup workflow is therefore the right
implementation for SMF / JCSMP clients that publish PERSISTENT
({@code DeliveryMode.PERSISTENT}) to
{@code compacted/lookup/<key>}, but it is NOT reachable via the
Solace REST {@code /REQUESTS/} endpoint.

For curl-based smoke testing, the MI's own REST KV API at
{@code GET /api/v1/kv/<key>} is the canonical entry point. It
returns the stored payload as the response body with
{@code x-compacted-topic} and {@code x-compacted-ingest-timestamp}
headers, or {@code 404} for a miss. No Solace round-trip; sub-
millisecond response. Documented in {@code README.md}'s
"Quick smoke-test recipes" section.

### Lab verification target

For SMF / JCSMP PERSISTENT lookup callers (the workflow's intended
client shape):

- Lookup queue {@code redeliveredMsgCount} unchanged per request.
- Lookup flow {@code ackedMsgCount} +1 per request.
- Reply published DIRECT to the requestor's
  {@code solace_replyTo}; visible on the
  {@code topic-compaction-mi-audit} client's {@code dataRxMsgCount}
  (the publisher session sends it).

### Architecture summary after V1.1.4

All four workflows now use the same consumer-side ack pattern:

| Workflow | Inbound queue | Output | Ack mechanism |
|---|---|---|---|
| Compaction | compaction.data | DirectAuditPublisher (audit) | AckHelper.accept |
| Replay - single REPLAY | compaction.commands | StreamBridge to output-3 (PERSISTENT) | AckHelper.accept |
| Replay - BULK_REPLAY | compaction.commands | StreamBridge to output-3 + DirectAuditPublisher (summary) | AckHelper.accept |
| Replay - DELETE | compaction.commands | DirectAuditPublisher (summary) | AckHelper.accept |
| Lookup | compaction.lookup | DirectAuditPublisher (reply) | AckHelper.accept |

The MI Framework's binder publish-ack chain is no longer in the
critical path for any inbound message's consumer-ack. Workflows
publish through routes that either:

1. Have guaranteed subscribers provisioned (StreamBridge to
   output-3 for replay messages where operators are expected to
   subscribe a queue to {@code <key>/compacted}), OR
2. Use DIRECT delivery to subscribers known to be online
   (audit, command summaries, lookup replies).

Failures in either path are logged but never block the inbound
ack.

## [1.1.3] - 2026-05-07

Bug fix on top of V1.1.2. Same architectural pattern, applied to
the SINGLE REPLAY path the V1.1.1 work missed.

### Fixed

- **SINGLE REPLAY commands triggered repeated republish to
  {@code <key>/compacted}.** A user-reported observation: a single
  {@code REPLAY} command produced the same replay payload arriving
  repeatedly on {@code <key>/compacted}. Same root cause as
  V1.1.1's BULK_REPLAY/DELETE bug: the workflow's output-1 binding
  emits a PERSISTENT publish, the broker silently discards it when
  no guaranteed subscriber is provisioned (typical for live debug
  with TryMe DIRECT subscribers), the publish-ack callback never
  fires, the inbound command-ack hangs, and the broker redelivers
  the command up to {@code maxRedeliveryCount=5} - each redelivery
  re-runs the replay.

  V1.1.1 had deliberately left REPLAY on the workflow output-1
  path under the assumption that operators would always provision
  a guaranteed subscriber on the replay destination. In practice
  the typical operator workflow uses TryMe (DIRECT-only) for live
  validation, which leaves the publish-ack chain hanging.

### Changed

- {@code CommandConsumerInterceptorFactory.handleSingleReplay()}:
  new method that runs {@link ReplayService#process(CommandEvent)}
  on the consumer side, builds a {@code MessageBuilder}-backed
  replay message with the destination + headers from the
  {@code Decision}, and sends it via
  {@link StreamBridge#send(String, Object)} to
  {@code BulkReplayService.FANOUT_BINDING} (the existing
  {@code output-3} fan-out binding). The command-ack is flushed
  immediately via {@code AckHelper.accept()}; the replay publish
  is fire-and-forget from the consumer's perspective.

  This is the same pattern BULK_REPLAY uses for its fan-out (and
  V1.1.0/V1.1.2 use for compaction): publish via
  {@code StreamBridge}, ack via {@code AcknowledgmentCallback}.

### Operator note: replay durability

The V1.1.3 path still publishes PERSISTENT to
{@code <key>/compacted}. If the operator's downstream subscriber
isn't provisioned with a guaranteed endpoint (queue with
matching subscription), the broker will discard the message - but
the COMMAND will still be acked exactly once and the replay loop
is broken. Operators who need replay-on-demand must subscribe a
queue to {@code <key>/compacted} (or the configured
{@code target-suffix}) BEFORE issuing the REPLAY command.

### Lab verification target

After this fix a single TryMe-published REPLAY command should
produce **exactly one** message on {@code <key>/compacted} (or
zero, if no subscriber is online), the command-queue's
{@code redeliveredMsgCount} should be unchanged, and the
command-flow's {@code ackedMsgCount} should increment by 1.

## [1.1.2] - 2026-05-07

Critical bug fix on top of V1.1.1. Same architectural principle,
correct implementation.

### Fixed

- **Inbound messages were processed up to 6 times each.** A user-
  reported observation: a single TryMe publish on
  {@code orders/v110-final/test/A} produced 6 distinct audit
  events with different {@code ingestTimestamp} values, all with
  outcome {@code UPSERTED}. Lab confirmation: queue
  {@code maxRedeliveryExceededDiscardedMsgCount} ticked up by 1
  per inbound message, and the txFlow showed {@code ackedMsgCount=0}
  - i.e. **the consumer never positively acknowledged a single
  message**. Six = 1 initial delivery + {@code maxRedeliveryCount=5}
  redeliveries before drop.

  Root cause: V1.1.0 assumed that returning {@code null} from the
  consumer-side {@code ConsumerBindingMessageInterceptor.after()}
  implicitly ACKed the inbound message. It does not. The MI
  Framework wraps the interceptor as a Spring Integration
  {@code ChannelInterceptor#preSend}; per the Spring contract a
  null return CANCELS the channel send, but the Solace binder's
  {@code JCSMPInboundChannelAdapter} treats the cancelled send as
  a delivery failure and the broker redelivers. The compaction
  workflow's queue-drain symptom from the lab tests (txUnacked=0
  within 470 ms) had been misread: the count dropped because the
  broker stopped waiting for acks on NACKed messages, not because
  the consumer had acked.

  Fix: explicitly flush the inbound's
  {@link org.springframework.integration.acks.AcknowledgmentCallback}
  with {@code ACCEPT} BEFORE returning null from the consumer
  interceptor. The Solace binder attaches a callback to every
  inbound message header; calling {@code acknowledge(ACCEPT)}
  positively acks the message at the broker (no redelivery), and
  the subsequent null-return suppresses the workflow output as
  before.

### Added

- New {@code com.solace.labs.mi.topiccompaction.util.AckHelper}
  utility. Single static method {@code accept(message)} that:
  - Looks up the {@code AcknowledgmentCallback} via the standard
    Spring Integration header key
    ({@code IntegrationMessageHeaderAccessor.ACKNOWLEDGMENT_CALLBACK
    = "acknowledgmentCallback"});
  - No-ops if the header is missing (defensive against
    test/mock messages);
  - No-ops if the callback is already in a final state
    ({@code isAcknowledged()} guard);
  - Catches any RuntimeException and logs at WARN so a flaky
    callback never fails the consumer chain.

### Changed

- {@code CompactionConsumerInterceptorFactory.after()}: invokes
  {@code AckHelper.accept(message)} after the KV upsert and the
  {@code DirectAuditPublisher.publishAudit} call, before
  returning null.

- {@code CommandConsumerInterceptorFactory.after()}: invokes
  {@code AckHelper.accept(message)} on the BULK_REPLAY, DELETE,
  and parse-failure paths before returning null. The SINGLE
  REPLAY path is unchanged - it returns the message so the
  workflow's output binding fires the binder publish-ack chain,
  which auto-flushes the inbound ack via the binder's normal
  pattern.

### Lab verification target

After this fix a single TryMe publish on
{@code orders/v110-final/test/A} should produce **exactly one**
audit event on {@code orders/v110-final/test/A/compacted-ack},
the queue's {@code redeliveredMsgCount} should be unchanged, and
the txFlow's {@code ackedMsgCount} should increment by 1.

### Operator note: DMQ routing

Investigation deferred but documented: V1.1.1's lab data showed
{@code maxRedeliveryExceededDiscardedMsgCount=635} and
{@code maxRedeliveryExceededToDmqMsgCount=0}, and the
{@code #DEAD_MSG_QUEUE} stayed at zero spool. The provisioner
sets {@code deliveryCountEnabled=true} +
{@code deadMsgQueue=#DEAD_MSG_QUEUE}, so the broker should route
max-redel-exceeded messages to the DMQ. The published messages
themselves may not be {@code dmqEligible} (the broker default
when neither sender nor queue config sets it explicitly is
non-DMQ-eligible). Tracking for V1.2.

## [1.1.1] - 2026-05-06

Bug fix on top of V1.1.0. Same architectural pattern, applied to
the second binder publish path the V1.1.0 work missed.

### Fixed

- **`BULK_REPLAY` and `DELETE` command events were not being
  acked.** The replay workflow's output binding (output-1) emits
  three observability documents - the bulk-replay summary on
  {@code topic-compaction/replay/bulk-result}, the delete summary
  on {@code topic-compaction/delete/result}, and the failure doc on
  {@code topic-compaction/replay/failed}. None of these typically
  have a guaranteed subscriber provisioned (they are intended as
  fire-and-forget operator observability). With nothing subscribed,
  the broker silently discards the PERSISTENT publish (counter
  {@code msgSpoolRxDiscardedMsgCount} on the MI client increments,
  no NACK fires), the MI Framework's
  {@code AsyncOutputSendingMessageHandler} waits the full
  {@code publish-timeout} window, and the inbound consumer-ack on
  the COMMAND event hangs. The command then redelivers up to
  {@code maxRedeliveryCount=5}, re-running the bulk replay or
  delete each time before the broker drops it. Lab measurement
  confirmed this produced ~44 redeliveries per command on average.

### Changed

- New {@code CommandConsumerInterceptorFactory} attached to
  {@code input-1}. Handles BULK_REPLAY, DELETE, and parse-failure
  command events on the consumer side, fires the summary /
  failure event fire-and-forget via the V1.1.0
  {@code DirectAuditPublisher} (DIRECT delivery, separate JCSMP
  session), and returns {@code null} from {@code after()} to
  short-circuit the workflow's downstream channel send. The
  inbound command-ack flushes within milliseconds. SINGLE REPLAY
  still flows through to the producer interceptor unchanged
  because {@code <key>/compacted} is durability-relevant.

- {@code DirectAuditPublisher.publishJsonDirect(topic,
  payloadObject, correlationId)}: new method for generic
  fire-and-forget JSON observability events. The payload is
  Jackson-serialised, sent with {@code DeliveryMode.DIRECT}, with
  an optional {@code x-original-correlation-id} user property.
  Used by the new command consumer interceptor for all three
  summary topics.

- {@code ReplayProducerInterceptorFactory}: still attached to
  {@code output-1} but now only services the SINGLE REPLAY
  command path. BULK_REPLAY, DELETE, and parse-failure branches
  remain in the class as a defence-in-depth fallback in case the
  consumer interceptor is bypassed (operator misconfig, direct
  StreamBridge call), but in normal operation those branches no
  longer fire because the consumer interceptor short-circuits.

### Test infrastructure

- Lab verification: BULK_REPLAY command, command-queue
  {@code txUnackedMsgCount} drained from 1 to 0 within 470 ms (vs.
  150 s + max-redel cycle in V1.1.0).
- Unit suite unchanged - the existing
  {@code ReplayProducerInterceptorTest} cases still pass because
  the producer interceptor's behaviour is preserved on the
  fall-through path.

## [1.1.0] - 2026-05-06

Architectural release. Decouples audit emission from the binder
publish path, eliminating the V1.0.x stuck-spool symptom at the
root rather than bounding it. Adds Testcontainers-based integration
coverage and tightens the redelivery -> DMQ contract.

### Architectural change: audit emission moved off the binder

V1.0.x emitted audits via the Spring Cloud Stream Solace binder's
output-0 path. The binder hardcodes outbound `DeliveryMode.PERSISTENT`
in `XMLMessageMapper.mapToSmf` (binder 5.11.0), and the MI Framework's
`AsyncOutputSendingMessageHandler` chains the consumer-ack on the
inbound message to the publish-ack on the audit. With Solace Cloud
10.x silently discarding JCSMP-from-MI-client publishes that route
back to the same compaction queue, the consumer-ack stayed pinned
in `txUnackedMsgCount` for the framework's full `publish-timeout`
window - up to 10 minutes per inbound burst at the V1.0.0 default,
30 s at V1.0.2's tightened default, and finally drained via the
`maxRedeliveryCount` cycle (5 retries x 30 s = ~150 s).

V1.1.0 moves audit emission to a SEPARATE JCSMP session with
`DeliveryMode.DIRECT`. The consumer-ack on the inbound message is
flushed as soon as the KV upsert completes - it has no dependency on
the audit publish-ack. The audit itself is fire-and-forget
observability: any publish failure is logged but never blocks the
durability path.

### Added

- **`DirectAuditPublisher`** (new component). Manages a separate
  JCSMP session with a distinct `clientName` (default suffix
  `-audit`), opens an `XMLMessageProducer`, and publishes audit JSON
  with `DeliveryMode.DIRECT`. Lifecycle hooks (`@PostConstruct`,
  `@PreDestroy`) tie the session to the application lifecycle; a
  failed startup logs WARN and leaves the publisher inert (audits
  are dropped) rather than blocking application startup.
  ([`compaction/DirectAuditPublisher.java`])

- **`topic-compaction.compaction.audit` config block.** New
  `enabled` flag (default `true`, backward-compat) lets operators
  flip audit emission off entirely. New `client-name-suffix` and
  `connect-timeout-millis` knobs tune the separate-session setup.
  ([`compaction/CompactionProperties.java`])

- **DMQ correctness in the broker provisioner.** Per-queue
  `maxRedeliveryCount` (default 5), `deliveryCountEnabled` (default
  `true` - critical, the V1.0.x default `false` caused max-redel
  messages to be DROPPED instead of routed to the DMQ), and
  `deadMsgQueue` (default `#DEAD_MSG_QUEUE`). The provisioner now
  pre-creates each referenced DMQ and PATCHes existing queues to
  apply the durability config on restart.
  ([`provisioning/BrokerProvisioner.java`,
  `provisioning/ProvisioningProperties.java`])

- **Testcontainers integration test.** `DirectAuditPublisherIT`
  spins up `solace/solace-pubsub-standard` via
  `org.testcontainers:junit-jupiter`, opens both a publisher and a
  subscriber session, and verifies that an audit message published
  via `DirectAuditPublisher` arrives on the subscribed audit topic
  within a sub-second budget. Runs in the failsafe
  `integration-test` phase (`mvn verify`).

### Changed

- **`CompactionConsumerInterceptorFactory`**: `after()` now performs
  the synchronous KV upsert, fires the audit via
  `DirectAuditPublisher`, and **returns `null`** to short-circuit
  the workflow's downstream channel send. The MI Framework wraps
  the consumer interceptor as a Spring Integration
  {@code ChannelInterceptor#preSend}; per the Spring contract, a
  null return from {@code preSend} suppresses the send-to-channel,
  which means the binder's
  {@code AsyncOutputSendingMessageHandler} is never invoked and
  the consumer-ack flushes as soon as
  {@code JCSMPInboundChannelAdapter} sees this method return.
  Result: end-to-end inbound-to-ack latency drops from
  ~30 s (V1.0.2) / ~150 s (V1.0.x with max-redel cycle) to a
  single-digit-millisecond KV write plus the JCSMP ack round-trip.
  ([`compaction/CompactionConsumerInterceptorFactory.java`])

- **`CompactionAuditProducerInterceptorFactory`**: rewritten as a
  pure SUPPRESSOR. `before()` returns `null` for every message,
  causing the binder to skip the publish on output-0 and complete
  the consumer-ack chain successfully. Audit JSON construction is
  no longer in this class.
  ([`compaction/CompactionAuditProducerInterceptorFactory.java`])

- **V1.0.2 binder tunings retained as defence-in-depth.**
  `pub_ack_time=30000`, `pub_ack_window_size=50`, and
  `publish-timeout=30000` are no longer on the critical path for
  the compaction workflow (audits are off the binder), but they
  remain the right defaults for the replay (output-1) and lookup
  (output-2) workflows that DO publish via the binder.

### Fixed

- **DMQ now actually catches poison messages.** V1.0.x set
  `maxRedeliveryCount=5` + `deadMsgQueue=#DEAD_MSG_QUEUE` on the
  queue, but the broker default `deliveryCountEnabled=false` meant
  max-redel-exceeded messages were silently DROPPED rather than
  routed to the DMQ. The provisioner now sets
  `deliveryCountEnabled=true` and PATCHes existing queues on every
  startup so the upgrade is automatic.

- **Consumer-ack drain time on inbound bursts.** Verified empirically
  in the lab: 5-message inbound burst now drains
  {@code txUnackedMsgCount} from 5 to 0 within ~470 ms, vs. ~30 s
  in V1.0.2 and ~150 s in V1.0.x. KV consistency unchanged: every
  inbound message is upserted exactly once before the consumer-ack
  flushes; if the upsert throws, the ack is suppressed and the
  message redelivers up to {@code maxRedeliveryCount=5} before the
  broker routes it to {@code #DEAD_MSG_QUEUE}.

### Operator note: audit-topic cascade is bounded but not eliminated

The audit topic ({@code <topic>/compacted-ack}) still matches a
broad data subscription pattern like {@code orders/>}, so the
broker spool routes every audit publish back into
{@code compaction.data}. With V1.1.0 the impact is bounded:

- Each cascading audit is recognised as a loop by
  {@code CompactionService.compact()} (the loop-protection header
  is set by {@code DirectAuditPublisher}) and SKIPPED;
- The consumer-ack on each cascading audit flushes immediately
  (same null-return path as inbound);
- The audit's audit suppression (V1.0.1 cascade-break,
  preserved in {@code DirectAuditPublisher}) means no further
  audit hops are generated.

Operators who want to eliminate the audit cascade entirely have two
options without touching the MI:

1. Subscribe their compaction queue to a pattern that does NOT
   cover the audit suffix - e.g. {@code orders/*/*} instead of
   {@code orders/>}, or scope by message type.
2. Set {@code topic-compaction.compaction.audit.enabled=false} if
   they don't need the audit feed at all. This stops the publisher
   entirely and removes the cascade source.

### Test infrastructure

- New unit test class `DirectAuditPublisherTest` with mocked
  `XMLMessageProducer`. Covers: payload shape, DIRECT delivery
  mode, loop-protection user property, `SKIPPED_LOOP` suppression,
  fire-and-forget exception swallowing, blank-topic dropping,
  audit-disabled short-circuit. 7 cases.
- `CompactionAuditProducerInterceptorTest` rewritten for the
  V1.1.0 suppressor contract: every outcome -> `null` from
  `before()`. 3 cases.
- New JaCoCo coverage exclusion for `DirectAuditPublisher`'s
  `start()` / `stop()` methods (pure JCSMP wiring covered by the
  Testcontainers integration test, not the unit suite).

## [1.0.2] - 2026-05-05

Tuning hotfix on top of V1.0.1. Resolves the `txUnackedMsgCount > 0`
stuck-spool symptom observed after the V1.0.1 cascade fix landed:
inbound messages were processed correctly (KV state up-to-date) but
the consumer-ack on `compaction.data` lingered for several seconds
before flushing. Root cause was the JCSMP publish-side timeout being
hit on the audit publish, holding the binder's ack chain.

### Changed

- **`pub_ack_time`**: now `30000` ms (was JCSMP default `2000`).
  The 2 s default is hostile under burst load: a 5-message ingress
  burst regularly saw the trailing audit publishes time out before
  the broker acked, even though the broker would have acked within
  tens of milliseconds had it been polled. The publish-timeout fired
  on the producer event handler, the binder routed the failure to
  the error channel, and only then did the consumer-ack flush. Net
  effect: `txUnackedMsgCount` and `msgSpoolUsage` lingered for
  seconds even though every KV write had already succeeded. 30 s is
  the operational "this is genuinely broken" threshold; under that,
  transient broker slowness is absorbed cleanly.
  ([`src/main/resources/application.yml`])

- **`pub_ack_window_size`**: tightened from `255` to `50`. The
  default window is sized for high-throughput streaming workloads;
  the compaction MI is bounded by ingestion, not publish. A smaller
  in-flight window lets the binder apply backpressure earlier on a
  slow broker, instead of saturating the publisher buffer and
  burning all of `pub_ack_time` to recover.
  ([`src/main/resources/application.yml`])

- **MI Framework `acknowledgment.publish-timeout`**: lowered from
  the framework default `600000` ms (10 minutes) to `30000` ms
  (30 s). This is the upper-bound timeout that
  `AsyncOutputSendingMessageHandler` enforces before resolving the
  consumer-ack with failure if no publish-ack callback fires.
  Surfaced during V1.0.2 verification: with the V1.0.0/V1.0.1
  audit-cascade still cleared but the audit topic
  (`<topic>/compacted-ack`) routed back to the same `compaction.data`
  queue, the broker silently discards the audit publish (counter
  `msgSpoolRxDiscardedMsgCount` increments, but no JCSMP NACK fires).
  Without an explicit failure callback, the MI Framework waited the
  full 10-minute default before flushing the consumer-ack via the
  error-channel - so `txUnackedMsgCount` stayed > 0 for 10 minutes
  per inbound burst. 30 s aligns the framework timeout with
  `pub_ack_time` and bounds the worst-case stuck-spool window. The
  underlying broker-discard root cause is logged below for V1.1
  follow-up.
  ([`src/main/resources/application.yml`])

### Investigation note: silent broker discard of audit publishes

Verified empirically against Solace Cloud broker 10.x in the lab:
when the audit topic pattern (`<topic>/compacted-ack`) matches the
data subscription on the same compaction queue, every audit publish
the MI emits via JCSMP is counted under the broker client's
`msgSpoolRxDiscardedMsgCount` and never reaches the queue's
`spooledMsgCount`. The broker neither completes the publish-ack nor
fires a NACK, so JCSMP's `pub_ack_time` does not trigger - only the
MI Framework's wall-clock `publish-timeout` eventually resolves the
chain. With the binder NACKing the inbound on publish-failure, the
message goes through the `maxRedeliveryCount=5` cycle (5 retries x
30 s = ~150 s) before the broker drops it. The discards persist
regardless of:

- `consumerAckPropagationEnabled` (toggling to `false` did not
  unblock).
- `noLocal` flow flag (already `false`).
- Queue ack-window state (well below `maxDeliveredUnackedMsgsPerFlow`).
- ACL profile (default-allow on publish + subscribe).
- VPN spool quota (335 B / 50 GB used).

**Counter-test isolating the JCSMP-from-MI-client path.** A REST
publish from the SOLACE_REST_HOST endpoint to a structurally
identical topic
(`orders/diag-audit/<ts>/X/compacted-ack`, marked
`Solace-Delivery-Mode: persistent`) is **accepted**: queue
`lastSpooledMsgId` advances, `spooledMsgCount` increments, the
message is delivered to the MI consumer flow. Same broker, same
VPN, same ACL profile, same matching subscription. The discard is
specific to the publish coming from the MI's own JCSMP session
(which is also the session subscribed to the queue). This narrows
the V1.1 fix to a **separate** JCSMP session for audit publishes -
sharing the consumer session would inherit the same discard
behavior.

The root cause at the broker layer is still unidentified. Working
hypothesis: a per-client publisher-side rule kicks in when a
PERSISTENT message published by client X would route back to a
queue X is currently consuming with unacked messages. The 30 s
`publish-timeout` plus 5x redelivery cap bounds the worst case to
~150 s of stuck-spool per inbound burst, and V1.1's separate-session
direct-audit publisher avoids the discard path entirely.

### Deferred to V1.1

- **Audit-publish via DIRECT delivery mode.** The Spring Cloud
  Stream Solace binder hardcodes outbound `DeliveryMode.PERSISTENT`
  in `XMLMessageMapper.mapToSmf()` (binder 5.11.0); there is no
  per-binding producer property and no Spring header that overrides
  this. A clean switch to DIRECT for the audit topic
  (`<topic>/compacted-ack`) would require a parallel
  `DirectAuditPublisher` bean that manages its own JCSMPSession and
  XMLMessageProducer, bypassing the binder for this single path.
  That is V1.1 work because (a) it owns its session lifecycle,
  reconnect, and error handling rather than reusing the binder's
  battle-tested plumbing, (b) it warrants Testcontainers-based
  integration coverage before shipping, and (c) it removes the
  dependency on the broker accepting the audit publish - DIRECT
  bypasses the spool entirely. The PERSISTENT path is acceptable
  in V1.0.x once the framework `publish-timeout` is realistic.

- **JCSMP keep-alive interval tuning.** The
  `ClientChannelProperties_KeepAliveIntervalInMillis` /
  `..._KeepAliveLimit` pair lives on the
  `JCSMPChannelProperties` sub-object, which is not reachable via
  the `api-properties` text-marshaling path
  (`JCSMPPropertiesTextMarshaling` logs "Skipping property key ...
  unknown" for those keys). The right hook is a
  `BeanPostProcessor<SpringJCSMPFactory>` that mutates the
  underlying `JCSMPProperties.CLIENT_CHANNEL_PROPERTIES` object
  before the session is created. The default 3 s / 3 = 9 s outage
  detection is acceptable for V1.0.x; tightening it is a V1.1
  hardening item.

## [1.0.1] - 2026-05-05

Hotfix release. Resolves the audit cascade discovered after V1.0.0
was deployed to Solace Cloud.

### Fixed

- **Audit cascade / redelivery storm.** When the operator's data
  subscription pattern (e.g. `orders/>`) covers the audit-suffix
  pattern (`orders/X/compacted-ack`), the audit message was
  re-ingested by the compaction queue, treated as a fresh inbound
  topic, and re-audited indefinitely. Each cascade hop generated
  another audit publish; the JCSMP publish-ack window (255)
  saturated, publish-acks timed out, the originating inbound
  message got NACKed, and got redelivered. Observed in the lab:
  43k+ redeliveries in 6 hours from a single stuck message.
  ([CompactionAuditProducerInterceptorFactory])

  Two complementary fixes:

  - The audit interceptor now suppresses emission for
    `SKIPPED_LOOP` outcomes. Loop-skipped messages are
    re-ingested ricochets that carry no operator-visible signal,
    and emitting an audit just generates the next cascade hop.
  - When an audit IS emitted (UPSERTED, SKIPPED_OUT_OF_ORDER,
    SKIPPED_NO_TOPIC), it now carries the same loop-protection
    header that replays do. If the audit's destination matches the
    data subscription pattern, the re-ingested copy is recognised
    by `CompactionService.compact` as a loop and skipped without
    a fresh audit.

### Added

- New unit test `suppressesAuditForSkippedLoopOutcome` documents
  the suppression contract.
- New unit test `emitsAuditForSkippedOutOfOrderWithLoopHeader`
  documents that "real" skip outcomes still surface as audits.

## [1.0.0] - 2026-05-05

The first production-ready release. Single-replica deployment;
HA is V2 (see ADR 0002). Highlights at a glance:

- **Three workflows**: compaction, replay (single + bulk +
  delete), lookup (request/reply).
- **REST KV surface** with read + admin role separation.
- **Per-prefix TTL retention** and streaming backup/restore.
- **Hardened K8s deployment** (`mi-solace-lab` namespace,
  read-only root FS, dropped capabilities, NetworkPolicy, PDB).
- **LGTM-stack observability**: Prometheus ServiceMonitor,
  SLO-based alerts, Grafana dashboard, OTLP traces, JSON logs.
- **Idempotent `start.sh` / `stop.sh`** with monitoring
  artifacts deployed alongside.
- 111 unit + integration tests, JaCoCo coverage gate, fully
  non-interactive smoke test, bash load harness.
- 12 user-facing docs + 5 ADRs.

### Phases (per Conventional Commits)

### Added

- Phase 0: project skeleton for v1.0.0 - dedicated `CLAUDE.md`,
  `CHANGELOG.md`, `.markdownlint.json`, and the ADR directory with
  `0001-architecture.md` and `0002-no-ha-in-v1.md`.
- Phase 1: REST controller now accepts both unencoded multi-segment
  paths (`/api/v1/kv/orders/created/A`) and URL-encoded slashes
  (`/api/v1/kv/orders%2Fcreated%2FA`). Implementation switches the
  mapping to Spring `PathPattern` style `/{*key}` and decodes any
  remaining percent-encoded chars in the controller.
- Phase 1: `RestExceptionHandler` (`@ControllerAdvice` scoped to the
  API package) translates known exceptions into RFC-7807
  `application/problem+json` responses with consistent title and
  detail fields.
- Phase 1: programmatic input validation on REST path and query
  parameters (`format`, `limit`) raises `IllegalArgumentException`
  which the exception handler converts to 400 problem details.
- Phase 1: `observability.MetricsConfig` registers a `@Primary`
  `PrometheusMeterRegistry` that shares the auto-configured
  `PrometheusRegistry`, so `/actuator/prometheus` exposes the MI's
  Micrometer counters and gauges. Common tags `application`,
  `version`, `namespace` are attached via a `MeterFilter`.
- Phase 1: `api.WebServerConfig` relaxes the Tomcat connector to
  `passthrough` encoded-solidus handling, and `api.HttpFirewallConfig`
  configures `StrictHttpFirewall` to allow URL-encoded slashes - both
  required for legacy clients sending `%2F` in path variables.
- Phase 1: liveness and readiness health groups (`/actuator/health/
  liveness`, `/actuator/health/readiness`). Readiness includes the
  Solace binder so Kubernetes holds traffic until bindings are UP.
- Phase 2: structured JSON logging via `logstash-logback-encoder`
  under the `k8s` and `prod` Spring profiles; pretty single-line
  console under `dev` and the default profile. MDC fields include
  `traceId`, `spanId`, `service`, `key`, and `command`.
- Phase 2: OpenTelemetry tracing pipeline with OTLP gRPC exporter.
  `application.yml` defaults the endpoint to `localhost:4317` so a
  missing collector does not crash the app; the K8s ConfigMap
  overrides to the in-cluster Tempo service.
- Phase 2: `observability.TracingConfig` registers the AOP aspects
  (`ObservedAspect`, `TimedAspect`, `CountedAspect`) so the Micrometer
  annotations on workflow entry points actually create spans.
- Phase 2: `@Observed` annotations on `CompactionService.compact`,
  `ReplayService.process`, and `LookupService.resolve` create the
  workflow-level spans. `MDC.MDCCloseable` populates structured
  context (`service`, `key`, `command`) for the duration of each call.
- Phase 2: `docs/OBSERVABILITY.md` -- metric reference, log schema,
  trace topology, configuration matrix, and troubleshooting table.
- Phase 2: 6 new `KvStoreControllerTest` cases exercising
  url-encoded keys, embedded slashes, the `?format=meta` query
  parameter, and limit-validation rejection.

### Changed

- Phase 1: `KvStoreController` mappings moved from `/{key}` and
  `/{key}/meta` to a single `/{*key}` with optional `?format=meta`
  query parameter. The `/meta` sub-path is removed (was already
  broken for slashed keys). See migration note below.
- Phase 1: `application.yml` keeps `management.defaults.metrics.export.
  enabled: false` and adds `management.prometheus.metrics.export.
  enabled: true` so Prometheus is the only registered exporter.
- Phase 1: actuator endpoint `prometheus` exposed read-only (Spring
  Boot 3 `access: read_only` style).

### Security

- Phase 1: explicit `StrictHttpFirewall` configuration in
  `HttpFirewallConfig` allows URL-encoded slashes only. All other
  hardening defaults (encoded percent-encoded chars, control
  characters, encoded period) remain in effect. Documented as safe
  in V1 because captured keys are never used as filesystem paths or
  shell arguments.
- (Full REST authentication arrives in Phase 4.)

### Migration Notes

- The legacy `GET /api/v1/kv/{key}/meta` endpoint is replaced by
  `GET /api/v1/kv/{key}?format=meta`. Operations scripts that hit the
  old path must be updated. Both URL-encoded and unencoded slashes
  are supported in the new mapping.

### Phase 3 - new commands and operations

#### Added

- Phase 3.1: JSON-Schema validation for command events. Schema lives
  at `src/main/resources/schemas/command-event-v1.json`, version 1.
  `CommandEventParser` validates inbound JSON before mapping it to
  `CommandEvent`; schema violations result in a structured failure
  document on `topic-compaction/replay/failed`.
- Phase 3.1: `pattern` field on `CommandEvent` (used by
  `BULK_REPLAY`); the legacy 3-argument constructor is preserved as
  an overload for backward compatibility with existing tests.
- Phase 3.2: `BULK_REPLAY` command. Iterates the KV store using a
  `SolacePatternMatcher` (Solace topic-style wildcards `*` and `>`)
  and republishes the latest record of every match via the
  `output-3` fanout binding. Throughput is capped by an optional
  client-supplied `rateLimit` (default 1000 msg/s; Bucket4j).
  Results in a JSON summary on
  `topic-compaction/replay/bulk-result`.
- Phase 3.2: `SolacePatternMatcher` with RocksDB prefix-iterator
  optimisation (longest non-wildcard prefix used as seek key).
- Phase 3.3: `DELETE` command. Single-key tombstone plus optional
  `options.cascade` Solace pattern for bulk delete. Result event on
  `topic-compaction/delete/result`.
- Phase 3.3: `topic_compaction_deletes_total` counter tracks all
  records tombstoned via the command path or the REST DELETE.
- Phase 3.4: TTL/Retention policy. Operator-tunable via
  `topic-compaction.retention.*`. Disabled by default; when enabled,
  a `RetentionService` background sweeper iterates the store on a
  fixed delay and evicts records past their TTL. Per-prefix rules
  override a default TTL with longest-prefix-first matching.
- Phase 3.4: `topic_compaction_retention_evicted_total` counter.
- Phase 3.5: Backup and restore tooling. Streaming line-delimited
  JSON format (one record per line; first line is a header with
  format version and timestamp). REST endpoints `POST
  /api/v1/admin/backup` and `POST /api/v1/admin/restore`.
- Phase 3: 30+ new unit tests across pattern matcher, bulk replay,
  delete service, retention sweeper, and backup roundtrip
  (105 tests total, was 67).

#### Changed

- Phase 3.1: `ReplayService.process(byte[])` delegates JSON parsing
  to `CommandEventParser`; the prior direct ObjectMapper call is
  gone.
- Phase 3.2: `ReplayProducerInterceptorFactory` now dispatches by
  command type:
  `REPLAY` -> `ReplayService`,
  `BULK_REPLAY` -> `BulkReplayService`,
  `DELETE` -> `DeleteCommandService`.
- Phase 3.2: `mi-config/application.yml` configures the `output-3`
  binding with a placeholder destination and explicit
  `producer.auto-startup: true` so `BulkReplayService` can publish
  via `StreamBridge` without a separate workflow.

#### Documentation

- `docs/COMMAND-EVENTS.md` rewritten for V1.0 - covers the JSON
  schema, all three command types, options reference, and
  end-to-end REST examples for `REPLAY` and `BULK_REPLAY`.

### Phase 4 - security, robustness, ops hardening

#### Added

- Phase 4.1: `WebSecurityConfig` and `SecurityProperties`. Two
  in-memory roles (`USER`, `ADMIN`) with HTTP Basic auth.
  Whitelist for `/actuator/health` and `/actuator/prometheus`. The
  framework's `SecurityAutoConfiguration` is excluded to avoid
  bean conflicts. ADR 0004 records the rationale.
- Phase 4.1: `MI_SECURITY_ENABLED`, `MI_USER_*`, `MI_ADMIN_*` env
  vars added to `.env.example` and the docker-compose mi-config.
  Disabled by default in dev mode; the K8s overlay enables it.
- Phase 4.2: `BrokerProvisioner` (`ApplicationRunner`) idempotently
  creates the workflow queues and topic subscriptions via SEMP
  v2 on startup. Conditional on
  `topic-compaction.provisioning.enabled`. 400 ("already exists")
  is treated as success.
- Phase 4.3: graceful shutdown wired - `server.shutdown=graceful`,
  `spring.lifecycle.timeout-per-shutdown-phase=25s`. `compose.yaml`
  sets `stop_grace_period=30s` and a healthcheck. The existing
  `RocksDbKvStore.@PreDestroy` already syncs the WAL before close.
- Phase 4.4: `StartupBanner` logs a one-shot summary of resolved
  config on `ApplicationReadyEvent`. Sensitive values (usernames)
  are masked. Gives operators sanity-check at boot.
- Phase 4.5: `consumer.concurrency: 1` on the command queue
  (input-1) so `BULK_REPLAY` cannot be parallelised across
  consumers, keeping the rate limiter deterministic.

### Phase 5 - Kubernetes deployment

#### Added

- `deploy/k8s/00-namespace.yaml` through `81-prometheusrule.yaml`
  - Namespace `mi-solace-lab` with PodSecurity `restricted`.
  - ConfigMap with the K8s overlay of `application.yml`.
  - Secret template (rendered via envsubst at deploy time;
    rendered file gitignored).
  - 10 Gi `ReadWriteOnce` PVC for RocksDB at
    `/var/lib/topic-compaction/rocksdb`.
  - Single-replica Deployment with `Recreate` strategy, hardened
    pod (non-root, read-only-rootFS, dropped capabilities,
    seccomp), liveness/readiness/startup probes.
  - ClusterIP Service exposing actuator port.
  - PodDisruptionBudget `minAvailable: 0` for clean drains.
  - NetworkPolicy: ingress from monitoring + same-namespace,
    egress to DNS, in-cluster Tempo (4317), and Solace Cloud
    SMF/REST/SEMP ports.
  - `ServiceMonitor` and `PrometheusRule` in the `monitoring`
    namespace with `prometheus: kube-prometheus` label so the
    operator picks them up.
  - Six initial alerts: pod absence, Solace binder down, skip
    rate, KV growth, lookup latency, pod memory.
- `deploy/k8s/scripts/start.sh` and `stop.sh` -- idempotent deploy
  and teardown. `start.sh` validates the env, renders the secret
  template, stamps a config-checksum annotation on the
  Deployment, applies all manifests, and waits for rollout.
  `stop.sh` removes monitoring artifacts then the workload, and
  optionally the PVC and namespace via flags.
- `Makefile` targets `k8s-deploy`, `k8s-status`, `k8s-logs`,
  `k8s-port-forward`, `k8s-restart`, `k8s-undeploy`,
  `k8s-undeploy-purge`.
- ADR 0003 (K8s deployment topology) and ADR 0004 (REST auth and
  role model).

#### Changed

- Image tag bumped from `1.0.0-SNAPSHOT` to `1.0.0` and pushed to
  `registry.solace.lab/sam-topic-compaction-mi:1.0.0`.
- `MetricsConfig.prometheusMeterRegistry` is now
  `@ConditionalOnBean(PrometheusRegistry.class)` so test contexts
  without the auto-config can still load.
- `TopicCompactionApplication` excludes the framework's
  `SecurityAutoConfiguration` (replaced by `WebSecurityConfig`).

#### Verified

- 105 unit tests green.
- Local docker-compose smoke test green with security disabled
  AND with security enabled (full role-matrix verified against
  the running container).
- K8s deployment in `mi-solace-lab` successfully rolled out in
  Rancher Desktop. Pod READY, PVC bound, ServiceMonitor + PrometheusRule
  visible in the `monitoring` namespace, security role matrix
  (10 checks) verified via port-forward.

### Phase 6 - Grafana dashboard, SLO alerts, runbook

#### Added

- `81-prometheusrule.yaml` rewritten into four groups:
  recording rules (`topic-compaction.recording` group), symptom
  alerts (pod absence, NotReady, memory), SLO alerts (compaction
  success rate, lookup p95, lookup miss ratio), capacity alerts
  (KV growth, PVC fill).
- Three recording rules computing SLIs once at scrape time:
  `topic_compaction:compaction_success_rate:5m`,
  `topic_compaction:lookup_p95_seconds:5m`,
  `topic_compaction:lookup_miss_ratio:5m`. Dashboards and alerts
  read the same series.
- Every alert now carries a `runbook` label that maps to a
  section in `docs/OPERATIONS.md`.
- `82-grafana-dashboard.yaml` -- ConfigMap with the
  `grafana_dashboard: "1"` label so the kube-prometheus-stack
  Grafana sidecar auto-imports it. Dashboard "Topic Compaction
  MI" with five rows: status stat-row, throughput (RED),
  latency, resources, storage. Templated by namespace + pod.
- `docs/OPERATIONS.md` -- runbook covering the SLO definitions,
  per-alert response (verify + recovery), routine ops
  (restart, credential rotation, retention), backup/restore
  procedure, disaster-recovery scenarios, and capacity planning.
- ADR 0005 -- SLO + alert strategy: SLI/SLO definitions, alert
  taxonomy (symptom / SLO / capacity), severity policy,
  recording-rule naming convention, and the rationale for
  deferring multi-window burn-rate alerts to a future iteration.
- `start.sh` and `stop.sh` updated to apply / remove the
  Grafana dashboard ConfigMap alongside the other monitoring
  artifacts.

### Phase 7 - test strategy + load harness

#### Added

- JaCoCo coverage plugin in `pom.xml` with a `mvn verify`
  threshold check (>= 75% line, >= 65% branch on the testable
  bundle). Spring `@Configuration` wiring classes are excluded
  because their behaviour is verified by integration tests, not
  unit tests.
- `EndToEndIntegrationTest` (6 cases) exercises the full service
  stack against a real per-test RocksDB instance:
  compaction-then-replay cycle, bulk-replay fanout, cascade
  delete, retention eviction, backup/restore roundtrip, and
  RocksDB persistence across a close+reopen.
- `examples/load-test.sh` -- bash + curl harness driving
  configurable producer load via the broker REST endpoint and
  sampling Prometheus metrics. Suitable for sanity load up to
  ~200 msg/s; production benchmarking should switch to sdkperf.
- `docs/PERFORMANCE.md` -- V1.0 baseline numbers
  (throughput, latency, resource use), bulk-replay benchmark
  table, capacity-planning rules of thumb, known performance
  limits, and explicit V1.1 future-work backlog.
- `Makefile` targets `verify`, `coverage`, `load-test`.

#### Changed

- `examples/smoke-test.sh` rewritten as fully non-interactive,
  exit-code-clean, with 10 assertions across health, compaction,
  replay, bulk-replay, tombstone, and admin/backup. Optional
  `--k8s` mode port-forwards the cluster service.
- `RocksDbKvStore.close()` visibility raised from package-private
  to public so integration tests outside the kvstore package can
  drive the close/reopen cycle.

#### Verified

- 111 tests green (was 105; +6 integration tests).
- Coverage check passes (`mvn verify` exits 0).
- Smoke test exits 0 with 10/10 assertions passing against the
  docker-compose deployment.
- Load test runs to completion with the expected throughput
  numbers logged in PERFORMANCE.md.

#### Deferred to V1.1

- Testcontainers-based integration tests with a real Solace
  broker. The `@SpringBootTest` setup conflicts with the MI
  Framework's auto-configuration; the existing
  `EndToEndIntegrationTest` covers the service-layer
  end-to-end, and `examples/smoke-test.sh` covers
  broker-integrated end-to-end.
- sdkperf-based load harness for sustained > 500 msg/s
  benchmarking.
- Per-workflow latency histograms (compaction, replay, lookup)
  separate from the generic `http.server.requests` series.

## [0.x] (pre-release MVP, V1)

The MVP shipped before this CHANGELOG was introduced. See git history
prior to commit `bf3859e` for the per-commit detail. High-level summary:

- Three workflows: Compaction, Replay (single only), Lookup.
- Direct REST surface for KV lookup/list/delete (with the slash-encoding
  caveat noted above).
- Docker-compose deployment, bring-your-own-broker.
- 61 unit tests across kvstore, compaction, replay, command, lookup, and
  api packages.
- Audit events on compaction, request/reply lookup, end-to-end smoke
  test.
