package com.solace.labs.mi.topiccompaction.compaction;

import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptorFactory;
import com.solace.labs.mi.topiccompaction.compaction.CompactionService.Result;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.ConsumerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Component;

import java.util.Map;

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
 * <p>The interceptor performs the KV-store update as a side effect and returns
 * an enriched message: the original payload plus a tiny header
 * ({@code x-compaction-result}) that the downstream
 * {@link CompactionAuditProducerInterceptorFactory producer interceptor} reads
 * to build the audit event.
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

    public CompactionConsumerInterceptorFactory(CompactionService service, CompactionProperties properties) {
        this.service = service;
        this.properties = properties;
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
            Result result = service.compact(message);
            return MessageBuilder.fromMessage(message)
                    .copyHeaders(Map.of(
                            COMPACTION_RESULT_HEADER, result.outcome().name(),
                            COMPACTION_TOPIC_HEADER, result.topic() == null ? "" : result.topic(),
                            COMPACTION_SIZE_HEADER, result.record() == null ? 0 : result.record().sizeBytes()
                    ))
                    .build();
        }
    }
}
