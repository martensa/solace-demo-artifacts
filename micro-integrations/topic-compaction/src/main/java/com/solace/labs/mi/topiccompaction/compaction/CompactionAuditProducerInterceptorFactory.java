package com.solace.labs.mi.topiccompaction.compaction;

import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptorFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.Set;

/**
 * V1.1.0: pure suppressor on the binder's compaction output binding.
 *
 * <p>Earlier versions of this class built an audit JSON document
 * and published it via the binder's PERSISTENT path on
 * {@code output-N}. That coupled the consumer-ack on the inbound
 * message to the audit publish-ack chain, and exposed the MI to a
 * silent broker discard when the audit topic
 * ({@code <topic>/compacted-ack}) routed back to the same
 * compaction queue ({@code msgSpoolRxDiscardedMsgCount} counter
 * incremented, no NACK fired, JCSMP {@code pub_ack_time} never
 * triggered). Net effect: consumer-ack pinned in
 * {@code txUnackedMsgCount} for the framework's full
 * {@code publish-timeout} window.
 *
 * <p>V1.1.0 moves audit emission to the consumer-side interceptor
 * via {@link DirectAuditPublisher} on a SEPARATE JCSMP session with
 * {@code DeliveryMode.DIRECT}. The binder's output-0 path is now
 * unused for compaction. This class still attaches as a producer
 * interceptor, but it returns {@code null} from {@code before()}
 * unconditionally so the binder skips the publish, the
 * {@code AsyncOutputSendingMessageHandler} short-circuits its
 * publish-ack-bound completable future, and the consumer-ack on
 * the inbound message flushes as soon as the consumer-side
 * interceptor returns.
 *
 * <p>The class is kept (rather than removed) for two reasons:
 *
 * <ul>
 *   <li>The MI Framework workflow definition for compaction wires
 *       {@code input-0 -> output-0}; without an interceptor
 *       returning null, the binder would attempt to publish the
 *       consumer-interceptor's enriched message on a placeholder
 *       topic.</li>
 *   <li>The hook is the right place to add a future telemetry
 *       counter for "compaction publishes suppressed", in case
 *       operators want to observe the binder-bypass count.</li>
 * </ul>
 */
@Component
public class CompactionAuditProducerInterceptorFactory implements ProducerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(CompactionAuditProducerInterceptorFactory.class);

    private final CompactionProperties properties;
    private final Set<String> outputBindingNames;

    public CompactionAuditProducerInterceptorFactory(CompactionProperties properties) {
        this.properties = properties;
        // Symmetrically derive the suppression target binding(s):
        // for every input-N configured for compaction, suppress the
        // matching output-N. This keeps operator config minimal:
        // only declare the input bindings.
        this.outputBindingNames = new HashSet<>();
        for (String input : properties.getBindingNames()) {
            if (input.startsWith("input-")) {
                outputBindingNames.add("output-" + input.substring("input-".length()));
            }
        }
    }

    @Override
    @Nullable
    public ProducerBindingMessageInterceptor createIfNecessary(String binderType, ProducerProperties producerProperties) {
        if (!"solace".equals(binderType)) {
            return null;
        }
        String bindingName = producerProperties.getBindingName();
        if (!outputBindingNames.contains(bindingName)) {
            return null;
        }
        log.info("Attaching CompactionPublishSuppressor to Solace producer binding: {} "
                + "(audit emission moved to DirectAuditPublisher in V1.1.0)", bindingName);
        return new Suppressor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    /**
     * Returns {@code null} for every message. The framework treats a
     * null return from {@code before()} as "no publish needed" and
     * completes the consumer-ack chain successfully. No bytes leave
     * the MI on the binder publish path; audits go via
     * {@link DirectAuditPublisher} from the consumer-side
     * interceptor.
     */
    private final class Suppressor implements ProducerBindingMessageInterceptor {
        @Override
        public Message<?> before(Message<?> message) {
            return null;
        }
    }
}
