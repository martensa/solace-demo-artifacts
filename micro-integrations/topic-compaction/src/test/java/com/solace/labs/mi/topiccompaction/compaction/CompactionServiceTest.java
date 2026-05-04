package com.solace.labs.mi.topiccompaction.compaction;

import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;

import java.nio.charset.StandardCharsets;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class CompactionServiceTest {

    private KvStore kvStore;
    private CompactionService service;
    private CompactionProperties props;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        props = new CompactionProperties();
        CompactionMetrics metrics = new CompactionMetrics(new SimpleMeterRegistry(), kvStore);
        service = new CompactionService(kvStore, props, metrics);
    }

    @Test
    void upsertsMessageKeyedByTopic() {
        Message<?> message = MessageBuilder.withPayload("hello".getBytes(StandardCharsets.UTF_8))
                .setHeader("solace_destination", "orders/created/1")
                .setHeader("content-type", "text/plain")
                .build();

        CompactionService.Result result = service.compact(message);

        assertThat(result.outcome()).isEqualTo(CompactionService.Outcome.UPSERTED);
        assertThat(result.topic()).isEqualTo("orders/created/1");

        CompactedRecord stored = kvStore.get("orders/created/1").orElseThrow();
        assertThat(new String(stored.payload(), StandardCharsets.UTF_8)).isEqualTo("hello");
        assertThat(stored.headers()).containsEntry("content-type", "text/plain");
    }

    @Test
    void replacesExistingValueOnRepeatedMessage() {
        Message<?> first = messageOf("k", "v1");
        Message<?> second = messageOf("k", "v2");

        service.compact(first);
        service.compact(second);

        assertThat(new String(kvStore.get("k").orElseThrow().payload(), StandardCharsets.UTF_8))
                .isEqualTo("v2");
    }

    @Test
    void skipsMessagesWithLoopProtectionHeader() {
        Message<?> replayed = MessageBuilder.withPayload("body".getBytes(StandardCharsets.UTF_8))
                .setHeader("solace_destination", "orders/1")
                .setHeader("x-compacted-replay", true)
                .build();

        CompactionService.Result result = service.compact(replayed);

        assertThat(result.outcome()).isEqualTo(CompactionService.Outcome.SKIPPED_LOOP);
        assertThat(kvStore.get("orders/1")).isEmpty();
    }

    @Test
    void skipsMessagesMissingTheDestinationHeader() {
        Message<?> badMessage = MessageBuilder.withPayload("x".getBytes(StandardCharsets.UTF_8))
                .build();

        CompactionService.Result result = service.compact(badMessage);

        assertThat(result.outcome()).isEqualTo(CompactionService.Outcome.SKIPPED_NO_TOPIC);
    }

    @Test
    void senderTimestampOrderingPreventsOlderOverwrites() {
        props.getOrdering().setHeader("senderTimestamp");

        // ingest a "newer" message first
        service.compact(messageOf("k", "newer", 1000L));
        // arrival of an older message must NOT overwrite
        CompactionService.Result older = service.compact(messageOf("k", "older", 500L));

        assertThat(older.outcome()).isEqualTo(CompactionService.Outcome.SKIPPED_OUT_OF_ORDER);
        assertThat(new String(kvStore.get("k").orElseThrow().payload(), StandardCharsets.UTF_8))
                .isEqualTo("newer");
    }

    @Test
    void senderTimestampOrderingAllowsNewerOverwrites() {
        props.getOrdering().setHeader("senderTimestamp");

        service.compact(messageOf("k", "older", 500L));
        service.compact(messageOf("k", "newer", 1000L));

        assertThat(new String(kvStore.get("k").orElseThrow().payload(), StandardCharsets.UTF_8))
                .isEqualTo("newer");
    }

    @Test
    void senderTimestampOrderingDisabledByDefault() {
        // Default config: header is empty - older messages overwrite newer ones (last-wins).
        Message<?> first = messageOf("k", "stamped-1000", 1000L);
        Message<?> second = messageOf("k", "stamped-500", 500L);

        service.compact(first);
        service.compact(second);

        assertThat(new String(kvStore.get("k").orElseThrow().payload(), StandardCharsets.UTF_8))
                .isEqualTo("stamped-500");
    }

    @Test
    void filtersInternalSpringHeadersFromStoredRecord() {
        Message<?> message = MessageBuilder.withPayload("x".getBytes(StandardCharsets.UTF_8))
                .setHeader("solace_destination", "k")
                .setHeader("scst_partition", "0") // SCS internal - must be filtered out
                .setHeader("deliveryAttempt", 1)  // framework internal - filtered
                .setHeader("user-property", "keep me")
                .build();

        service.compact(message);
        Optional<CompactedRecord> stored = kvStore.get("k");

        assertThat(stored).isPresent();
        assertThat(stored.get().headers()).doesNotContainKey("scst_partition");
        assertThat(stored.get().headers()).doesNotContainKey("deliveryAttempt");
        assertThat(stored.get().headers()).doesNotContainKey("id");
        assertThat(stored.get().headers()).doesNotContainKey("timestamp");
        assertThat(stored.get().headers()).containsEntry("user-property", "keep me");
    }

    private static Message<?> messageOf(String topic, String body) {
        return MessageBuilder.withPayload(body.getBytes(StandardCharsets.UTF_8))
                .setHeader("solace_destination", topic)
                .build();
    }

    private static Message<?> messageOf(String topic, String body, long senderTs) {
        return MessageBuilder.withPayload(body.getBytes(StandardCharsets.UTF_8))
                .setHeader("solace_destination", topic)
                .setHeader("senderTimestamp", senderTs)
                .build();
    }
}
