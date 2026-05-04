package com.solace.labs.mi.topiccompaction.replay;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ReplayServiceTest {

    private KvStore kvStore;
    private ReplayService service;
    private ReplayProperties props;
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        props = new ReplayProperties();
        objectMapper = new ObjectMapper();
        CompactionMetrics metrics = new CompactionMetrics(new SimpleMeterRegistry(), kvStore);
        service = new ReplayService(kvStore, props, objectMapper, metrics);
    }

    @Test
    void replaysWithCompactedSuffixByDefault() {
        seed("orders/created/12345", "the-payload");

        ReplayService.Decision decision = service.process(replayCommand("orders/created/12345"));

        assertThat(decision.success()).isTrue();
        assertThat(decision.destination()).isEqualTo("orders/created/12345/compacted");
        assertThat(new String(decision.payload(), StandardCharsets.UTF_8)).isEqualTo("the-payload");
    }

    @Test
    void setsLoopProtectionHeaderOnReplay() {
        seed("k", "x");
        ReplayService.Decision decision = service.process(replayCommand("k"));
        assertThat(decision.headers()).containsEntry("x-compacted-replay", true);
    }

    @Test
    void setsRewrittenSolaceDestinationHeader() {
        seed("k", "x");
        ReplayService.Decision decision = service.process(replayCommand("k"));
        assertThat(decision.headers()).containsEntry("solace_destination", "k/compacted");
    }

    @Test
    void honorsCustomDestinationSuffixOption() {
        seed("k", "x");
        byte[] cmd = """
                { "command": "REPLAY", "key": "k",
                  "options": { "destinationSuffix": "/custom" } }
                """.getBytes(StandardCharsets.UTF_8);
        ReplayService.Decision decision = service.process(cmd);
        assertThat(decision.destination()).isEqualTo("k/custom");
    }

    @Test
    void preservesOriginalHeadersByDefault() {
        kvStore.put("k", new CompactedRecord(
                "p".getBytes(StandardCharsets.UTF_8),
                Map.of("custom-header", "custom-value", "content-type", "text/plain"),
                "k", 100L, null));

        ReplayService.Decision decision = service.process(replayCommand("k"));
        assertThat(decision.headers()).containsEntry("custom-header", "custom-value");
        assertThat(decision.headers()).containsEntry("content-type", "text/plain");
    }

    @Test
    void dropsOriginalHeadersWhenIncludeFalse() {
        kvStore.put("k", new CompactedRecord(
                "p".getBytes(StandardCharsets.UTF_8),
                Map.of("custom-header", "custom-value"),
                "k", 100L, null));

        byte[] cmd = """
                { "command": "REPLAY", "key": "k",
                  "options": { "includeOriginalHeaders": false } }
                """.getBytes(StandardCharsets.UTF_8);

        ReplayService.Decision decision = service.process(cmd);
        assertThat(decision.headers()).doesNotContainKey("custom-header");
        assertThat(decision.headers()).containsEntry("solace_destination", "k/compacted");
    }

    @Test
    void addsCorrelationIdWhenPresent() {
        seed("k", "x");
        byte[] cmd = """
                { "command": "REPLAY", "key": "k",
                  "options": { "correlationId": "trace-abc" } }
                """.getBytes(StandardCharsets.UTF_8);
        ReplayService.Decision decision = service.process(cmd);
        assertThat(decision.headers()).containsEntry("x-original-correlation-id", "trace-abc");
    }

    @Test
    void failsWhenKeyNotInStore() {
        ReplayService.Decision decision = service.process(replayCommand("never-stored"));
        assertThat(decision.success()).isFalse();
        assertThat(decision.failure()).contains("never-stored");
    }

    @Test
    void failsOnMalformedJson() {
        byte[] cmd = "not json".getBytes(StandardCharsets.UTF_8);
        ReplayService.Decision decision = service.process(cmd);
        assertThat(decision.success()).isFalse();
        assertThat(decision.failure()).contains("Invalid command JSON");
    }

    @Test
    void failsOnUnsupportedCommand() {
        byte[] cmd = """
                { "command": "DELETE", "key": "x" }
                """.getBytes(StandardCharsets.UTF_8);
        ReplayService.Decision decision = service.process(cmd);
        assertThat(decision.success()).isFalse();
        assertThat(decision.failure()).contains("not supported in V1");
    }

    @Test
    void failsOnMissingKey() {
        byte[] cmd = """
                { "command": "REPLAY" }
                """.getBytes(StandardCharsets.UTF_8);
        ReplayService.Decision decision = service.process(cmd);
        assertThat(decision.success()).isFalse();
        assertThat(decision.failure()).contains("key is required");
    }

    @Test
    void failureDocumentIsValidJson() throws Exception {
        byte[] doc = service.renderFailureDocument("oops");
        @SuppressWarnings("unchecked")
        Map<String, Object> parsed = objectMapper.readValue(doc, Map.class);
        assertThat(parsed).containsEntry("status", "failed").containsEntry("reason", "oops");
    }

    private void seed(String key, String body) {
        kvStore.put(key, new CompactedRecord(
                body.getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", key),
                key, 100L, null));
    }

    private byte[] replayCommand(String key) {
        return ("{\"command\":\"REPLAY\",\"key\":\"" + key + "\"}").getBytes(StandardCharsets.UTF_8);
    }
}
