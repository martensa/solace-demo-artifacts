package com.solace.labs.mi.topiccompaction.compaction;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.stream.binder.BinderHeaders;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;

import java.util.Map;

import static com.solace.labs.mi.topiccompaction.compaction.CompactionConsumerInterceptorFactory.COMPACTION_RESULT_HEADER;
import static com.solace.labs.mi.topiccompaction.compaction.CompactionConsumerInterceptorFactory.COMPACTION_SIZE_HEADER;
import static com.solace.labs.mi.topiccompaction.compaction.CompactionConsumerInterceptorFactory.COMPACTION_TOPIC_HEADER;
import static org.assertj.core.api.Assertions.assertThat;

class CompactionAuditProducerInterceptorTest {

    private CompactionAuditProducerInterceptorFactory factory;
    private ObjectMapper objectMapper;
    private CompactionProperties props;

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        props = new CompactionProperties();
        factory = new CompactionAuditProducerInterceptorFactory(props, objectMapper);
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
    void rewritesPayloadAndDestinationToAuditEvent() throws Exception {
        ProducerProperties out0 = new ProducerProperties();
        out0.populateBindingName("output-0");
        ProducerBindingMessageInterceptor interceptor = factory.createIfNecessary("solace", out0);

        Message<?> input = MessageBuilder.withPayload("original payload".getBytes())
                .setHeader(COMPACTION_RESULT_HEADER, "UPSERTED")
                .setHeader(COMPACTION_TOPIC_HEADER, "orders/created/12345")
                .setHeader(COMPACTION_SIZE_HEADER, 16)
                .setHeader("solace_destination", "orders/created/12345")
                .build();

        Message<?> rewritten = interceptor.before(input);

        // Destination must be the original topic + audit suffix
        assertThat(rewritten.getHeaders().get("solace_destination"))
                .isEqualTo("orders/created/12345/compacted-ack");
        assertThat(rewritten.getHeaders().get(BinderHeaders.TARGET_DESTINATION))
                .isEqualTo("orders/created/12345/compacted-ack");
        assertThat(rewritten.getHeaders().get("content-type")).isEqualTo("application/json");

        // V1.0.1: every audit message carries the loop-protection
        // header so that re-ingesting the audit (which can match the
        // data subscription pattern, e.g. `orders/X/compacted-ack`
        // matches `orders/>`) is recognised by CompactionService and
        // SKIPPED instead of upserted as a new key.
        assertThat(rewritten.getHeaders())
                .containsEntry(props.getLoopProtectionHeader(), true);

        // Payload must be a JSON document with the compaction metadata
        @SuppressWarnings("unchecked")
        Map<String, Object> auditDoc = objectMapper.readValue(
                (byte[]) rewritten.getPayload(), Map.class);
        assertThat(auditDoc).containsEntry("topic", "orders/created/12345");
        assertThat(auditDoc).containsEntry("outcome", "UPSERTED");
        assertThat(auditDoc).containsEntry("sizeBytes", 16);
        assertThat(auditDoc).containsKey("ingestTimestamp");
    }

    @Test
    void suppressesAuditForSkippedLoopOutcome() {
        // V1.0.1 cascade-break: SKIPPED_LOOP messages are re-ingested
        // copies of our own audits / replays. Emitting an audit for
        // them just generates the next cascade hop (audit -> matched
        // by `orders/>` -> re-consumed -> SKIPPED_LOOP -> audit ->
        // ...). The interceptor returns null to drop the publish.
        ProducerProperties out0 = new ProducerProperties();
        out0.populateBindingName("output-0");
        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", out0);

        Message<?> skipped = MessageBuilder.withPayload(new byte[0])
                .setHeader(COMPACTION_RESULT_HEADER, "SKIPPED_LOOP")
                .setHeader(COMPACTION_TOPIC_HEADER, "orders/1")
                .setHeader(COMPACTION_SIZE_HEADER, 0)
                .build();

        assertThat(interceptor.before(skipped)).isNull();
    }

    @Test
    void emitsAuditForSkippedOutOfOrderWithLoopHeader() throws Exception {
        // SKIPPED_OUT_OF_ORDER is a real signal (producer clock
        // skew, late delivery). The audit fires so operators can
        // alert on it. The audit still carries the loop-protection
        // header so the re-ingest of `<topic>/compacted-ack` doesn't
        // cascade.
        ProducerProperties out0 = new ProducerProperties();
        out0.populateBindingName("output-0");
        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", out0);

        Message<?> skipped = MessageBuilder.withPayload(new byte[0])
                .setHeader(COMPACTION_RESULT_HEADER, "SKIPPED_OUT_OF_ORDER")
                .setHeader(COMPACTION_TOPIC_HEADER, "orders/1")
                .setHeader(COMPACTION_SIZE_HEADER, 0)
                .build();

        Message<?> rewritten = interceptor.before(skipped);
        assertThat(rewritten).isNotNull();
        assertThat(rewritten.getHeaders())
                .containsEntry(props.getLoopProtectionHeader(), true);
        @SuppressWarnings("unchecked")
        Map<String, Object> auditDoc = objectMapper.readValue(
                (byte[]) rewritten.getPayload(), Map.class);
        assertThat(auditDoc).containsEntry(
                "outcome", "SKIPPED_OUT_OF_ORDER");
    }
}
