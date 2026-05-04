package com.solace.labs.mi.topiccompaction.compaction;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptorFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.BinderHeaders;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.GenericMessage;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Rewrites compaction-workflow output into an audit event:
 * <ul>
 *   <li>Destination: {@code <original-topic><audit-suffix>}</li>
 *   <li>Payload: small JSON document describing the compaction outcome</li>
 *   <li>Headers: framework headers + compaction metadata; original payload
 *       headers are dropped to keep the audit event lightweight</li>
 * </ul>
 *
 * <p>If the compaction service skipped the message (loop / out-of-order /
 * missing topic), the audit event is still emitted - downstream observers can
 * count skips. To suppress audit events for skips entirely, configure the
 * operator-side workflow to filter via SpEL.
 */
@Component
public class CompactionAuditProducerInterceptorFactory implements ProducerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(CompactionAuditProducerInterceptorFactory.class);
    private static final String SOLACE_DESTINATION_HEADER = "solace_destination";

    private final CompactionProperties properties;
    private final ObjectMapper objectMapper;
    private final Set<String> outputBindingNames;

    public CompactionAuditProducerInterceptorFactory(CompactionProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        // Symmetrically derive the audit producer binding(s): for every input-N
        // configured for compaction, attach to the matching output-N. This keeps
        // operator config minimal: only declare the input bindings.
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
        log.info("Attaching CompactionAuditInterceptor to Solace producer binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor implements ProducerBindingMessageInterceptor {
        @Override
        public Message<?> before(Message<?> message) {
            String outcome = (String) message.getHeaders().getOrDefault(
                    CompactionConsumerInterceptorFactory.COMPACTION_RESULT_HEADER,
                    CompactionService.Outcome.UPSERTED.name());
            String topic = (String) message.getHeaders().getOrDefault(
                    CompactionConsumerInterceptorFactory.COMPACTION_TOPIC_HEADER, "");
            Object sizeObj = message.getHeaders().get(
                    CompactionConsumerInterceptorFactory.COMPACTION_SIZE_HEADER);
            int sizeBytes = sizeObj instanceof Number n ? n.intValue() : 0;

            Map<String, Object> auditPayload = new LinkedHashMap<>();
            auditPayload.put("topic", topic);
            auditPayload.put("outcome", outcome);
            auditPayload.put("sizeBytes", sizeBytes);
            auditPayload.put("ingestTimestamp", System.currentTimeMillis());

            byte[] payloadBytes;
            try {
                payloadBytes = objectMapper.writeValueAsBytes(auditPayload);
            } catch (JsonProcessingException e) {
                throw new IllegalStateException("Failed to serialize audit payload", e);
            }

            String auditDestination = topic.isBlank()
                    ? "topic-compaction/audit/no-topic"
                    : topic + properties.getAuditSuffix();

            Map<String, Object> auditHeaders = new LinkedHashMap<>();
            auditHeaders.put(SOLACE_DESTINATION_HEADER, auditDestination);
            auditHeaders.put(BinderHeaders.TARGET_DESTINATION, auditDestination);
            auditHeaders.put("content-type", "application/json");
            auditHeaders.put(CompactionConsumerInterceptorFactory.COMPACTION_RESULT_HEADER, outcome);

            return new GenericMessage<>(payloadBytes, auditHeaders);
        }
    }
}
