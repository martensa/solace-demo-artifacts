package com.solace.labs.mi.topiccompaction.lookup;

import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.messaging.support.MessageBuilder;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class LookupServiceTest {

    private KvStore kvStore;
    private LookupService service;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        service = new LookupService(kvStore, new LookupProperties(),
                new CompactionMetrics(new SimpleMeterRegistry(), kvStore));
    }

    @Test
    void resolvesKeyFromHeader() {
        kvStore.put("orders/1", record("orders/1", "found"));

        LookupService.Result result = service.resolve(MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "orders/1")
                .build());

        assertThat(result.found()).isTrue();
        assertThat(new String(result.payload(), StandardCharsets.UTF_8)).isEqualTo("found");
    }

    @Test
    void resolvesKeyFromTopicTail() {
        kvStore.put("orders/1", record("orders/1", "found"));

        LookupService.Result result = service.resolve(MessageBuilder.withPayload(new byte[0])
                .setHeader("solace_destination", "compacted/lookup/orders/1")
                .build());

        assertThat(result.found()).isTrue();
        assertThat(new String(result.payload(), StandardCharsets.UTF_8)).isEqualTo("found");
    }

    @Test
    void preferHeaderOverTopicTail() {
        kvStore.put("from-header", record("from-header", "header-wins"));
        kvStore.put("from-topic", record("from-topic", "topic-loses"));

        LookupService.Result result = service.resolve(MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "from-header")
                .setHeader("solace_destination", "compacted/lookup/from-topic")
                .build());

        assertThat(new String(result.payload(), StandardCharsets.UTF_8)).isEqualTo("header-wins");
    }

    @Test
    void notFoundResponseHasFlagsAndJsonBody() {
        LookupService.Result result = service.resolve(MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "missing")
                .build());

        assertThat(result.found()).isFalse();
        assertThat(result.headers()).containsEntry("x-compaction-status", "not-found");
        assertThat(result.headers().get("x-compaction-reason").toString()).contains("missing");
        assertThat(new String(result.payload(), StandardCharsets.UTF_8))
                .contains("\"status\":\"not-found\"");
    }

    @Test
    void notFoundWhenNoKeyProvided() {
        LookupService.Result result = service.resolve(MessageBuilder.withPayload(new byte[0]).build());
        assertThat(result.found()).isFalse();
        assertThat(result.headers().get("x-compaction-reason").toString()).contains("missing key");
    }

    @Test
    void includesOriginalHeadersOnHit() {
        kvStore.put("k", new CompactedRecord(
                "x".getBytes(StandardCharsets.UTF_8),
                Map.of("custom-header", "custom-value", "content-type", "text/plain"),
                "k", 100L, null));

        LookupService.Result result = service.resolve(MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "k")
                .build());

        assertThat(result.headers()).containsEntry("custom-header", "custom-value");
        assertThat(result.headers()).containsEntry("content-type", "text/plain");
        assertThat(result.headers()).containsEntry("x-compaction-status", "found");
        assertThat(result.headers()).containsEntry("x-compaction-key", "k");
    }

    private static CompactedRecord record(String topic, String body) {
        return new CompactedRecord(
                body.getBytes(StandardCharsets.UTF_8),
                Map.of(),
                topic, 100L, null);
    }
}
