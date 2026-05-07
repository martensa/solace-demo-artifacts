package com.solace.labs.mi.topiccompaction.compaction;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.solacesystems.jcsmp.BytesMessage;
import com.solacesystems.jcsmp.DeliveryMode;
import com.solacesystems.jcsmp.JCSMPException;
import com.solacesystems.jcsmp.JCSMPFactory;
import com.solacesystems.jcsmp.JCSMPProperties;
import com.solacesystems.jcsmp.JCSMPSession;
import com.solacesystems.jcsmp.JCSMPStreamingPublishCorrelatingEventHandler;
import com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation;
import com.solacesystems.jcsmp.SDTMap;
import com.solacesystems.jcsmp.Topic;
import com.solacesystems.jcsmp.XMLMessageProducer;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Fire-and-forget audit publisher running on a SEPARATE JCSMP
 * session from the binder. Bypasses three V1.0.x problems in one
 * step:
 *
 * <ul>
 *   <li>The Spring Cloud Stream Solace binder hardcodes outbound
 *       {@code DeliveryMode.PERSISTENT} (binder 5.11.0,
 *       {@code XMLMessageMapper.mapToSmf}). DIRECT is not reachable
 *       through the binder; we publish via raw JCSMP.</li>
 *   <li>Same-session publishes that route back to the consuming
 *       queue are silently discarded by Solace Cloud 10.x brokers
 *       ({@code msgSpoolRxDiscardedMsgCount} increments, no NACK,
 *       JCSMP {@code pub_ack_time} never fires). A separate session
 *       has a different {@code clientName} and is treated as an
 *       independent publisher.</li>
 *   <li>The MI Framework's {@code AsyncOutputSendingMessageHandler}
 *       chains the consumer-ack to the publish-ack, so a hung
 *       audit publish keeps the inbound message in
 *       {@code txUnackedMsgCount} for the full
 *       {@code publish-timeout} window. Decoupling the audit emission
 *       from the binder's output-0 path lets the consumer-ack flush
 *       as soon as the KV write succeeds.</li>
 * </ul>
 *
 * <p>Lifecycle: a {@link JCSMPSession} is opened once at
 * {@code @PostConstruct} time, the {@link XMLMessageProducer} is
 * cached on the bean, and both are closed in
 * {@code @PreDestroy}. Reconnect is delegated to JCSMP itself via
 * the application's existing {@code reconnect-retries: -1}
 * configuration.
 *
 * <p>Failure model: {@link #publishAudit} catches every checked
 * and unchecked exception. The audit is observability, not
 * durability; if the broker is unreachable or the producer is mid-
 * reconnect, we lose the audit but never block the consumer-ack on
 * the inbound message.
 */
@Component
public class DirectAuditPublisher {

    private static final Logger log = LoggerFactory.getLogger(DirectAuditPublisher.class);

    private final JCSMPProperties baseProperties;
    private final ObjectMapper objectMapper;
    private final CompactionProperties properties;
    private final SolaceContextPropagation propagation;

    private volatile JCSMPSession session;
    private volatile XMLMessageProducer producer;

    public DirectAuditPublisher(JCSMPProperties baseProperties,
                                 ObjectMapper objectMapper,
                                 CompactionProperties properties,
                                 SolaceContextPropagation propagation) {
        this.baseProperties = baseProperties;
        this.objectMapper = objectMapper;
        this.properties = properties;
        this.propagation = propagation;
    }

    @PostConstruct
    public void start() {
        if (!properties.getAudit().isEnabled()) {
            log.info("DirectAuditPublisher: audit.enabled=false, skipping session setup");
            return;
        }
        try {
            // Clone() returns Object via JCSMPPropertyMap.clone();
            // cast to JCSMPProperties is safe because that's the
            // concrete subclass exposed as a Spring @Bean by
            // SolaceJavaAutoConfiguration.
            JCSMPProperties props = (JCSMPProperties)
                    baseProperties.clone();
            // Distinct client name so the broker treats this as a
            // separate publisher, not the same one consuming
            // compaction.data. Falls back to a synthesised value if
            // the binder didn't set one explicitly.
            String baseClient = props.getStringProperty(
                    JCSMPProperties.CLIENT_NAME);
            if (baseClient == null || baseClient.isBlank()) {
                baseClient = "topic-compaction-mi";
            }
            props.setProperty(JCSMPProperties.CLIENT_NAME,
                    baseClient + properties.getAudit().getClientNameSuffix());
            // The audit publisher is publish-only. We don't need any
            // GD subscriber capability; turn off the AD-flow setup
            // so we don't pay the connect-time penalty for it.
            props.setProperty(JCSMPProperties.PUB_ACK_WINDOW_SIZE, 1);

            this.session = JCSMPFactory.onlyInstance().createSession(props);
            this.session.connect();
            this.producer = session.getMessageProducer(new SilentEventHandler());
            log.info("DirectAuditPublisher: session connected as clientName={}",
                    props.getStringProperty(JCSMPProperties.CLIENT_NAME));
        } catch (JCSMPException | RuntimeException e) {
            log.warn("DirectAuditPublisher: failed to open session - audits will be dropped: {}",
                    e.getMessage());
            // Leave session/producer null. publishAudit short-
            // circuits; the application keeps starting. This is the
            // right tradeoff: we never want a broker hiccup to
            // prevent the MI from coming up - the inbound consumer
            // path is what matters.
        }
    }

    @PreDestroy
    public void stop() {
        try {
            if (producer != null) {
                producer.close();
            }
        } catch (RuntimeException e) {
            log.debug("DirectAuditPublisher: producer close threw: {}", e.getMessage());
        }
        try {
            if (session != null) {
                session.closeSession();
            }
        } catch (RuntimeException e) {
            log.debug("DirectAuditPublisher: session close threw: {}", e.getMessage());
        }
    }

    /**
     * Publish a single audit event. Fire-and-forget: any failure
     * (broker unavailable, session disconnected, payload encoding
     * error) is logged at WARN and swallowed so the caller's
     * consumer-ack flow is never blocked.
     *
     * @param topic     original inbound topic
     * @param outcome   compaction outcome
     * @param sizeBytes payload size of the stored record (0 if not
     *                  applicable)
     */
    public void publishAudit(String topic, CompactionService.Outcome outcome, int sizeBytes) {
        if (!properties.getAudit().isEnabled() || producer == null) {
            // Disabled or session never came up. Drop silently.
            return;
        }
        // V1.0.1 cascade-break: SKIPPED_LOOP messages are
        // re-ingested ricochets. Emitting an audit for them just
        // generates the next cascade hop. With the audit pipeline
        // now on a SEPARATE session this is less critical (the
        // separate session sidesteps the broker discard), but the
        // suppression is still semantically correct: a skipped-as-
        // loop message has no operator-visible signal worth
        // auditing.
        if (outcome == CompactionService.Outcome.SKIPPED_LOOP) {
            return;
        }
        if (topic == null || topic.isBlank()) {
            return;
        }

        try {
            BytesMessage msg = JCSMPFactory.onlyInstance()
                    .createMessage(BytesMessage.class);
            msg.setData(buildPayload(topic, outcome, sizeBytes));
            msg.setHTTPContentType("application/json");
            msg.setDeliveryMode(DeliveryMode.DIRECT);

            // Loop-protection header carries through to the audit
            // even though the separate-session path makes a self-
            // cascade impossible (different clientName, no consumer
            // flow on this session). Keeping the header is
            // defence-in-depth: any future operator subscribing
            // an audit-replay queue with the data subscription
            // pattern still gets the loop-skip behaviour for free.
            //
            // V1.2.0: also inject the active W3C trace context
            // (traceparent / tracestate / baggage) so downstream
            // audit subscribers see the audit span as a child of
            // the inbound's trace.
            SDTMap userProps = JCSMPFactory.onlyInstance().createMap();
            String loopHeader = properties.getLoopProtectionHeader();
            if (loopHeader != null && !loopHeader.isBlank()) {
                userProps.putBoolean(loopHeader, true);
            }
            propagation.injectInto(userProps);
            msg.setProperties(userProps);

            String auditTopic = topic + properties.getAuditSuffix();
            Topic dest = JCSMPFactory.onlyInstance().createTopic(auditTopic);
            producer.send(msg, dest);
        } catch (JsonProcessingException | JCSMPException | RuntimeException e) {
            log.warn("DirectAuditPublisher: failed to publish audit for topic={} outcome={}: {}",
                    topic, outcome, e.getMessage());
        }
    }

    private byte[] buildPayload(String topic,
                                 CompactionService.Outcome outcome,
                                 int sizeBytes) throws JsonProcessingException {
        return objectMapper.writeValueAsBytes(new AuditPayload(
                topic, outcome.name(), sizeBytes, System.currentTimeMillis()));
    }

    /**
     * Fully-flexible fire-and-forget DIRECT publish. Used by the
     * lookup workflow to send the KV record back to a request's
     * {@code solace_replyTo} destination without gating the inbound
     * consumer-ack on the publish-ack.
     *
     * <p>Same DIRECT semantics as {@link #publishAudit}: the broker
     * skips the spool, no pub-ack is generated, lossy if no live
     * subscriber. For request/reply flows the requestor IS the
     * subscriber (Solace REST {@code /REQUESTS/...} keeps a temp
     * queue open until reply or timeout), so DIRECT delivers
     * cleanly.
     *
     * @param topic            destination topic (e.g. the request's
     *                         {@code solace_replyTo})
     * @param payload          raw payload bytes
     * @param contentType      optional HTTP content type
     * @param userProperties   optional Solace user properties to
     *                         set on the message; values are
     *                         converted via {@code SDTMap.put}'s
     *                         type-aware overloads
     * @param correlationId    optional JCSMP correlation-id to
     *                         echo back to the requestor
     */
    public void publishDirectBytes(String topic,
                                    byte[] payload,
                                    String contentType,
                                    java.util.Map<String, Object> userProperties,
                                    String correlationId) {
        if (!properties.getAudit().isEnabled() || producer == null) {
            return;
        }
        if (topic == null || topic.isBlank() || payload == null) {
            return;
        }
        try {
            BytesMessage msg = JCSMPFactory.onlyInstance()
                    .createMessage(BytesMessage.class);
            msg.setData(payload);
            if (contentType != null && !contentType.isBlank()) {
                msg.setHTTPContentType(contentType);
            }
            msg.setDeliveryMode(DeliveryMode.DIRECT);
            if (correlationId != null && !correlationId.isBlank()) {
                msg.setCorrelationId(correlationId);
            }
            // V1.2.0: always allocate the SDT map so we can inject
            // the trace context, even if the caller passed no
            // explicit user properties.
            SDTMap sdt = JCSMPFactory.onlyInstance().createMap();
            if (userProperties != null) {
                for (java.util.Map.Entry<String, Object> e :
                        userProperties.entrySet()) {
                    Object v = e.getValue();
                    if (v == null) continue;
                    if (v instanceof Boolean b) {
                        sdt.putBoolean(e.getKey(), b);
                    } else if (v instanceof Integer i) {
                        sdt.putInteger(e.getKey(), i);
                    } else if (v instanceof Long l) {
                        sdt.putLong(e.getKey(), l);
                    } else {
                        sdt.putString(e.getKey(), v.toString());
                    }
                }
            }
            propagation.injectInto(sdt);
            msg.setProperties(sdt);

            Topic dest = JCSMPFactory.onlyInstance().createTopic(topic);
            producer.send(msg, dest);
        } catch (JCSMPException | RuntimeException e) {
            log.warn("DirectAuditPublisher: failed to publish bytes to topic={}: {}",
                    topic, e.getMessage());
        }
    }

    /**
     * Generic fire-and-forget JSON publish for observability events
     * other than the per-message audit. Used for command-handling
     * summaries (BULK_REPLAY result, DELETE result, parse-failure
     * doc) where the publish-ack must NOT gate the consumer-ack on
     * the inbound command.
     *
     * <p>Same DIRECT semantics as {@link #publishAudit}: the broker
     * skips the spool, no pub-ack is generated, lossy if no live
     * subscriber. Operators who need durable observability should
     * provision a queue with a subscription on the relevant topic
     * (e.g. {@code topic-compaction/replay/bulk-result}).
     *
     * @param topic            destination topic
     * @param payloadObject    Jackson-serialisable JSON document
     * @param correlationId    optional; sets {@code x-original-
     *                         correlation-id} as a user property
     */
    public void publishJsonDirect(String topic,
                                   Object payloadObject,
                                   String correlationId) {
        if (!properties.getAudit().isEnabled() || producer == null) {
            return;
        }
        if (topic == null || topic.isBlank() || payloadObject == null) {
            return;
        }
        try {
            BytesMessage msg = JCSMPFactory.onlyInstance()
                    .createMessage(BytesMessage.class);
            msg.setData(objectMapper.writeValueAsBytes(payloadObject));
            msg.setHTTPContentType("application/json");
            msg.setDeliveryMode(DeliveryMode.DIRECT);

            // V1.2.0: always allocate the user-property map and
            // inject the W3C trace context. Add the optional
            // correlation-id only if provided.
            SDTMap userProps = JCSMPFactory.onlyInstance().createMap();
            if (correlationId != null && !correlationId.isBlank()) {
                userProps.putString("x-original-correlation-id",
                        correlationId);
            }
            propagation.injectInto(userProps);
            msg.setProperties(userProps);

            Topic dest = JCSMPFactory.onlyInstance().createTopic(topic);
            producer.send(msg, dest);
        } catch (JsonProcessingException | JCSMPException | RuntimeException e) {
            log.warn("DirectAuditPublisher: failed to publish JSON event to topic={}: {}",
                    topic, e.getMessage());
        }
    }

    /**
     * Compact JSON shape kept stable across V1.0.x and V1.1.x for
     * downstream consumers. Field names match the original
     * {@code CompactionAuditProducerInterceptorFactory} payload.
     */
    public record AuditPayload(String topic, String outcome,
                                int sizeBytes, long ingestTimestamp) {}

    /**
     * No-op handler. With {@code DeliveryMode.DIRECT} there are no
     * pub-ack callbacks; the handler exists only because
     * {@link JCSMPSession#getMessageProducer} requires one.
     */
    private static final class SilentEventHandler
            implements JCSMPStreamingPublishCorrelatingEventHandler {
        @Override
        public void responseReceivedEx(Object key) { /* no-op */ }

        @Override
        public void handleErrorEx(Object key, JCSMPException cause, long timestamp) {
            log.debug("DirectAuditPublisher async error: {}", cause.getMessage());
        }
    }
}
