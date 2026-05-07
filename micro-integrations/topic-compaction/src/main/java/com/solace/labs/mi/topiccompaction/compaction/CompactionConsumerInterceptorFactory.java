package com.solace.labs.mi.topiccompaction.compaction;

import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptorFactory;
import com.solace.labs.mi.topiccompaction.compaction.CompactionService.Result;
import com.solace.labs.mi.topiccompaction.util.AckHelper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.ConsumerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

/**
 * Wires the {@link CompactionService} into the Solace consumer binding(s)
 * configured for compaction.
 *
 * <p>Activation rule: only attaches when {@code binderType == "solace"} AND the
 * binding's name is in {@link CompactionProperties#getBindingNames()}. This keeps
 * the interceptor scoped to the compaction workflow only - other Solace
 * consumers in the MI (replay command queue, lookup request queue) are
 * unaffected.
 *
 * <p>V1.1.0 architectural change: audit emission moved from the
 * binder's output-0 producer interceptor INTO this consumer-side
 * interceptor. The consumer-ack on the inbound message must NOT
 * depend on the audit publish completing - the durability contract
 * is "ACK as soon as the message is in the KV store". The
 * downstream {@link CompactionAuditProducerInterceptorFactory} now
 * returns null unconditionally so the binder publish path on
 * output-0 is suppressed and the inbound ack flushes immediately
 * after this method returns.
 *
 * <p>Audit emission itself happens via {@link DirectAuditPublisher},
 * which uses a SEPARATE JCSMP session and {@code DeliveryMode.DIRECT}
 * - so the V1.0.x broker-discard cycle (PERSISTENT publish from the
 * same session that consumes the queue) is sidestepped entirely.
 */
@Component
public class CompactionConsumerInterceptorFactory implements ConsumerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(CompactionConsumerInterceptorFactory.class);

    /** Header carrying the compaction outcome handed off to the producer interceptor. */
    public static final String COMPACTION_RESULT_HEADER = "x-compaction-result";
    public static final String COMPACTION_TOPIC_HEADER = "x-compaction-topic";
    public static final String COMPACTION_SIZE_HEADER = "x-compaction-size-bytes";

    private final CompactionService service;
    private final CompactionProperties properties;
    private final DirectAuditPublisher auditPublisher;

    public CompactionConsumerInterceptorFactory(CompactionService service,
                                                 CompactionProperties properties,
                                                 DirectAuditPublisher auditPublisher) {
        this.service = service;
        this.properties = properties;
        this.auditPublisher = auditPublisher;
    }

    @Override
    @Nullable
    public ConsumerBindingMessageInterceptor createIfNecessary(String binderType, ConsumerProperties consumerProperties) {
        if (!"solace".equals(binderType)) {
            return null;
        }
        String bindingName = consumerProperties.getBindingName();
        if (!properties.getBindingNames().contains(bindingName)) {
            return null;
        }
        log.info("Attaching CompactionInterceptor to Solace consumer binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor implements ConsumerBindingMessageInterceptor {
        @Override
        public Message<?> after(Message<?> message) {
            // 1) Synchronous KV upsert. If this throws, the inbound is
            //    NACKed by the framework -> redelivered -> max-redel
            //    -> DMQ. Durability contract honoured.
            Result result = service.compact(message);

            // 2) Fire-and-forget audit on a SEPARATE JCSMP session
            //    with DeliveryMode.DIRECT. The publisher catches all
            //    failures internally; this call cannot throw and
            //    cannot block the consumer-ack flush.
            int sizeBytes = result.record() == null ? 0 : result.record().sizeBytes();
            auditPublisher.publishAudit(result.topic(), result.outcome(), sizeBytes);

            // 3) Manually flush the inbound consumer-ack BEFORE
            //    returning null. V1.1.0 assumed null-return from
            //    preSend implicitly ACKs the inbound, but it does
            //    not - it only suppresses the channel send, and the
            //    JCSMPInboundChannelAdapter treats the cancelled
            //    send as a failure (broker redelivers up to
            //    maxRedeliveryCount=5). Lab confirmed: 6 audit
            //    events per inbound message in V1.1.0/V1.1.1.
            //    AckHelper.accept() looks up the inbound's
            //    AcknowledgmentCallback (set on every Solace inbound
            //    by the binder) and calls acknowledge(ACCEPT). After
            //    that the null-return is safe.
            AckHelper.accept(message);
            return null;
        }
    }
}
