package com.solace.labs.mi.topiccompaction.compaction;

import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * V1.1.0 contract: the producer interceptor on the compaction
 * output binding is now a pure SUPPRESSOR. Audit emission moved to
 * the consumer-side interceptor + {@link DirectAuditPublisher}, so
 * the binder publish path must short-circuit (return null) for
 * every message - regardless of outcome - to keep the consumer-ack
 * decoupled from any output publish-ack.
 */
class CompactionAuditProducerInterceptorTest {

    private CompactionAuditProducerInterceptorFactory factory;
    private CompactionProperties props;

    @BeforeEach
    void setUp() {
        props = new CompactionProperties();
        factory = new CompactionAuditProducerInterceptorFactory(props);
    }

    @Test
    void onlyAttachesToOutputBindingsMatchingConfiguredInputs() {
        // Default config: bindingNames = {input-0} -> only output-0 should match
        ProducerProperties out0 = new ProducerProperties();
        out0.populateBindingName("output-0");
        ProducerProperties out2 = new ProducerProperties();
        out2.populateBindingName("output-2");

        assertThat(factory.createIfNecessary("solace", out0)).isNotNull();
        assertThat(factory.createIfNecessary("solace", out2)).isNull();
    }

    @Test
    void doesNotAttachToNonSolaceBinder() {
        ProducerProperties out0 = new ProducerProperties();
        out0.populateBindingName("output-0");
        assertThat(factory.createIfNecessary("kafka", out0)).isNull();
    }

    @Test
    void suppressesEveryPublishRegardlessOfOutcome() {
        ProducerProperties out0 = new ProducerProperties();
        out0.populateBindingName("output-0");
        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", out0);

        for (CompactionService.Outcome outcome : CompactionService.Outcome.values()) {
            Message<?> msg = MessageBuilder.withPayload("anything".getBytes())
                    .setHeader(CompactionConsumerInterceptorFactory.COMPACTION_RESULT_HEADER,
                            outcome.name())
                    .setHeader(CompactionConsumerInterceptorFactory.COMPACTION_TOPIC_HEADER,
                            "orders/created/1")
                    .setHeader(CompactionConsumerInterceptorFactory.COMPACTION_SIZE_HEADER, 8)
                    .build();
            assertThat(interceptor.before(msg))
                    .as("Suppressor must return null for outcome=%s", outcome)
                    .isNull();
        }
    }
}
