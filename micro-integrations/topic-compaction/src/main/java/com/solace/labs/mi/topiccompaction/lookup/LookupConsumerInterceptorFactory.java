package com.solace.labs.mi.topiccompaction.lookup;

import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptorFactory;
import com.solace.labs.mi.topiccompaction.compaction.DirectAuditPublisher;
import com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation;
import com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation.InboundScope;
import com.solace.labs.mi.topiccompaction.util.AckHelper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.ConsumerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * V1.1.4: handles lookup requests on the consumer side, publishes
 * the response via the separate-session DIRECT publisher, and
 * manually flushes the consumer-ack.
 *
 * <p>The architecture mirrors V1.1.0/V1.1.2 (compaction) and
 * V1.1.1/V1.1.3 (replay/bulk/delete): the workflow's binder publish
 * path is incompatible with destinations that have only DIRECT
 * subscribers (Solace REST {@code /REQUESTS/...} temp reply queue
 * is exactly that). The broker silently discards PERSISTENT
 * publishes to such destinations, the publish-ack callback never
 * fires, and the inbound consumer-ack pinned in
 * {@code txUnackedMsgCount} until the framework's
 * {@code publish-timeout} - then the broker redelivers up to
 * {@code maxRedeliveryCount=5} before dropping. Lab measurement
 * confirmed: lookup requests via REST REQUESTS endpoint resulted
 * in 504 Reply Wait Timeout 100% of the time, with
 * {@code ackedMsgCount=0} on the lookup flow.
 *
 * <p>Fix: do the work consumer-side, publish the reply DIRECT
 * (matching the requestor's DIRECT subscription on the temp
 * reply queue), manually ACCEPT the inbound, return null to
 * suppress the workflow output.
 */
@Component
public class LookupConsumerInterceptorFactory
        implements ConsumerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(
            LookupConsumerInterceptorFactory.class);

    private static final String SOLACE_REPLY_TO_HEADER = "solace_replyTo";
    private static final String SOLACE_CORRELATION_ID_HEADER = "solace_correlationId";
    private static final String NO_REPLY_TO_FALLBACK =
            "topic-compaction/lookup/no-reply-to";

    private final LookupService service;
    private final DirectAuditPublisher publisher;
    private final LookupProperties properties;
    private final SolaceContextPropagation propagation;

    public LookupConsumerInterceptorFactory(LookupService service,
                                             DirectAuditPublisher publisher,
                                             LookupProperties properties,
                                             SolaceContextPropagation propagation) {
        this.service = service;
        this.publisher = publisher;
        this.properties = properties;
        this.propagation = propagation;
    }

    @Override
    @Nullable
    public ConsumerBindingMessageInterceptor createIfNecessary(
            String binderType, ConsumerProperties consumerProperties) {
        if (!"solace".equals(binderType)) {
            return null;
        }
        String bindingName = consumerProperties.getBindingName();
        if (!properties.getBindingNames().contains(bindingName)) {
            return null;
        }
        log.info("Attaching LookupConsumerInterceptor to Solace consumer "
                + "binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor implements ConsumerBindingMessageInterceptor {
        @Override
        public Message<?> after(Message<?> message) {
            // V1.2.0: extract upstream W3C trace context from the
            // request, start a CONSUMER receive span. The DIRECT
            // reply inherits and injects the trace context.
            try (InboundScope ignored = propagation.extractAndStart(
                    message, "lookup.inbound")) {
                return doResolve(message);
            }
        }

        private Message<?> doResolve(Message<?> message) {
            try {
                LookupService.Result result = service.resolve(message);

                Object replyTo = message.getHeaders().get(
                        SOLACE_REPLY_TO_HEADER);
                String destination = replyTo == null
                        ? NO_REPLY_TO_FALLBACK
                        : replyTo.toString();

                Object correlationId = message.getHeaders().get(
                        SOLACE_CORRELATION_ID_HEADER);
                String correlationIdStr = correlationId == null
                        ? null
                        : correlationId.toString();

                // Build the user-property bag from the result's
                // headers. content-type comes from the result.headers
                // for not-found responses; for hits, the original
                // record's headers carry through (minus framework-
                // only fields, already filtered by CompactionService).
                Map<String, Object> userProps = new LinkedHashMap<>();
                String contentType = null;
                for (Map.Entry<String, Object> e : result.headers().entrySet()) {
                    if ("content-type".equalsIgnoreCase(e.getKey())) {
                        contentType = e.getValue() == null
                                ? null
                                : e.getValue().toString();
                        continue;
                    }
                    userProps.put(e.getKey(), e.getValue());
                }

                publisher.publishDirectBytes(
                        destination,
                        result.payload(),
                        contentType,
                        userProps,
                        correlationIdStr);
            } catch (RuntimeException e) {
                log.error("LookupConsumerInterceptor: resolve/publish failed: {}",
                        e.getMessage());
            } finally {
                // Flush the inbound consumer-ack regardless of the
                // publish outcome. Lookup is a request/reply pattern;
                // a failed publish means the requestor will time out
                // (504), which is the right error signal - we MUST
                // NOT redeliver and re-execute the lookup.
                AckHelper.accept(message);
            }
            return null;
        }
    }
}
