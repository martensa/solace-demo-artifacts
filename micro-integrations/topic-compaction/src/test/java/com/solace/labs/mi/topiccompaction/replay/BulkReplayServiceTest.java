package com.solace.labs.mi.topiccompaction.replay;

import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.command.CommandType;
import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.stream.function.StreamBridge;
import org.springframework.messaging.Message;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class BulkReplayServiceTest {

    private KvStore kvStore;
    private StreamBridge streamBridge;
    private List<Message<?>> sent;
    private BulkReplayService service;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        streamBridge = mock(StreamBridge.class);
        sent = new ArrayList<>();
        when(streamBridge.send(eq(BulkReplayService.FANOUT_BINDING),
                any(Message.class)))
                .thenAnswer(inv -> {
                    sent.add(inv.getArgument(1));
                    return true;
                });
        ReplayProperties props = new ReplayProperties();
        CompactionMetrics metrics = new CompactionMetrics(
                new SimpleMeterRegistry(), kvStore);
        service = new BulkReplayService(
                kvStore, props, streamBridge, metrics,
                new com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation(
                        io.micrometer.tracing.Tracer.NOOP,
                        io.micrometer.tracing.propagation.Propagator.NOOP));
    }

    @Test
    void replaysAllKeysMatchingPattern() {
        seed("orders/created/A", "a-payload");
        seed("orders/created/B", "b-payload");
        seed("orders/created/C", "c-payload");
        seed("invoices/X", "x-payload");

        BulkReplayService.BulkResult result = service.execute(
                bulkCommand("orders/created/*"));

        assertThat(result.isSuccess()).isTrue();
        assertThat(result.matched()).isEqualTo(3);
        assertThat(result.replayed()).isEqualTo(3);
        assertThat(result.failed()).isZero();
        assertThat(sent).hasSize(3);
    }

    @Test
    void multiLevelWildcardMatchesNested() {
        seed("orders/created/A", "a");
        seed("orders/created/A/B", "ab");
        seed("orders/updated/X/Y", "xy");
        seed("invoices/X", "x");

        BulkReplayService.BulkResult result = service.execute(
                bulkCommand("orders/>"));

        assertThat(result.matched()).isEqualTo(3);
        assertThat(result.replayed()).isEqualTo(3);
        List<String> destinations = sent.stream()
                .map(m -> (String) m.getHeaders()
                        .get("solace_destination"))
                .toList();
        assertThat(destinations).containsExactlyInAnyOrder(
                "orders/created/A/compacted",
                "orders/created/A/B/compacted",
                "orders/updated/X/Y/compacted");
    }

    @Test
    void replayMessagesCarryLoopProtectionHeader() {
        seed("orders/created/A", "a");
        service.execute(bulkCommand("orders/created/*"));

        assertThat(sent).hasSize(1);
        assertThat(sent.get(0).getHeaders())
                .containsEntry("x-compacted-replay", true)
                .containsEntry("x-bulk-replay", true);
    }

    @Test
    void emptyPatternMatchesNothing() {
        BulkReplayService.BulkResult result = service.execute(
                bulkCommand("doesnotexist/>"));

        assertThat(result.matched()).isZero();
        assertThat(result.replayed()).isZero();
        assertThat(sent).isEmpty();
    }

    @Test
    void invalidPatternIsRejectedGracefully() {
        BulkReplayService.BulkResult result = service.execute(
                bulkCommand("orders/>/created"));

        assertThat(result.isSuccess()).isFalse();
        assertThat(result.error()).contains("Invalid pattern");
        assertThat(sent).isEmpty();
    }

    @Test
    void missingPatternIsRejected() {
        BulkReplayService.BulkResult result = service.execute(
                new CommandEvent(CommandType.BULK_REPLAY,
                        null, null, Map.of()));

        assertThat(result.isSuccess()).isFalse();
        assertThat(result.error()).contains("pattern is required");
    }

    @Test
    void honorsCustomDestinationSuffix() {
        seed("orders/A", "x");
        service.execute(new CommandEvent(
                CommandType.BULK_REPLAY, null, "orders/*",
                Map.of("destinationSuffix", "/replayed")));

        assertThat(sent).hasSize(1);
        assertThat(sent.get(0).getHeaders())
                .containsEntry("solace_destination", "orders/A/replayed");
    }

    @Test
    void preservesOriginalHeadersByDefault() {
        kvStore.put("orders/A", new CompactedRecord(
                "x".getBytes(StandardCharsets.UTF_8),
                Map.of("custom-header", "custom-value"),
                "orders/A", 100L, null));

        service.execute(bulkCommand("orders/*"));

        assertThat(sent).hasSize(1);
        assertThat(sent.get(0).getHeaders())
                .containsEntry("custom-header", "custom-value");
    }

    private void seed(String key, String body) {
        kvStore.put(key, new CompactedRecord(
                body.getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", key),
                key, 100L, null));
    }

    private static CommandEvent bulkCommand(String pattern) {
        return new CommandEvent(CommandType.BULK_REPLAY, null,
                pattern, Map.of());
    }
}
