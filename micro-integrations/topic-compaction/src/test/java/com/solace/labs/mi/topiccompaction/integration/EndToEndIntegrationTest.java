package com.solace.labs.mi.topiccompaction.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.labs.mi.topiccompaction.admin.BackupService;
import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.command.CommandEventParser;
import com.solace.labs.mi.topiccompaction.command.CommandType;
import com.solace.labs.mi.topiccompaction.compaction.CompactionProperties;
import com.solace.labs.mi.topiccompaction.compaction.CompactionService;
import com.solace.labs.mi.topiccompaction.delete.DeleteCommandService;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.kvstore.RocksDbKvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import com.solace.labs.mi.topiccompaction.replay.BulkReplayService;
import com.solace.labs.mi.topiccompaction.replay.ReplayProperties;
import com.solace.labs.mi.topiccompaction.replay.ReplayService;
import com.solace.labs.mi.topiccompaction.retention.RetentionProperties;
import com.solace.labs.mi.topiccompaction.retention.RetentionService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.cloud.stream.function.StreamBridge;
import org.springframework.core.io.ClassPathResource;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.GenericMessage;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * Integration tests covering the full lifecycle of a compacted
 * record across multiple services with a real {@link RocksDbKvStore}
 * in a per-test temp directory. Exercises the persistent path that
 * the unit tests (which use {@code CaffeineKvStore}) skip.
 *
 * <p>Out of scope here: Solace broker integration. See
 * {@code examples/smoke-test.sh} for end-to-end testing against a
 * real broker.
 */
class EndToEndIntegrationTest {

    @TempDir
    Path tempDir;

    private RocksDbKvStore kvStore;
    private CompactionMetrics metrics;
    private CompactionService compactionService;
    private ReplayService replayService;
    private BulkReplayService bulkReplayService;
    private DeleteCommandService deleteService;
    private BackupService backupService;
    private RetentionService retentionService;
    private CommandEventParser parser;
    private List<Message<?>> sentMessages;
    private MutableClock clock;

    @BeforeEach
    void setUp() throws Exception {
        // Real RocksDB in a per-test temp directory. @TempDir
        // cleans up after the test.
        KvStoreProperties kvProps = new KvStoreProperties();
        kvProps.getRocksdb().setPath(
                tempDir.resolve("rocksdb").toString());
        kvStore = new RocksDbKvStore(kvProps);
        kvStore.open();

        ObjectMapper objectMapper = new ObjectMapper();
        SimpleMeterRegistry meterRegistry = new SimpleMeterRegistry();
        metrics = new CompactionMetrics(meterRegistry, kvStore);

        CompactionProperties compactionProps = new CompactionProperties();
        compactionService = new CompactionService(
                kvStore, compactionProps, metrics);

        ReplayProperties replayProps = new ReplayProperties();
        parser = new CommandEventParser(objectMapper,
                new ClassPathResource("schemas/command-event-v1.json"));
        parser.init();
        replayService = new ReplayService(kvStore, replayProps,
                objectMapper, parser, metrics);

        sentMessages = new ArrayList<>();
        StreamBridge streamBridge = mock(StreamBridge.class);
        when(streamBridge.send(eq(BulkReplayService.FANOUT_BINDING),
                any(Message.class)))
                .thenAnswer(inv -> {
                    sentMessages.add(inv.getArgument(1));
                    return true;
                });
        bulkReplayService = new BulkReplayService(
                kvStore, replayProps, streamBridge, metrics,
                new com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation(
                        io.micrometer.tracing.Tracer.NOOP,
                        io.micrometer.tracing.propagation.Propagator.NOOP));

        deleteService = new DeleteCommandService(kvStore, metrics);
        backupService = new BackupService(kvStore, objectMapper);

        clock = new MutableClock(System.currentTimeMillis());
        RetentionProperties retentionProps = new RetentionProperties();
        retentionService = new RetentionService(
                kvStore, retentionProps, metrics, clock);
    }

    @AfterEach
    void tearDown() {
        if (kvStore != null) {
            kvStore.close();
        }
    }

    @Test
    void compactionThenReplayCycle() {
        compactionService.compact(messageOnTopic(
                "orders/created/X1", "first-payload"));
        compactionService.compact(messageOnTopic(
                "orders/created/X1", "second-payload"));

        // RocksDB.size() is approximate; assert state via key
        // lookup which is exact.
        assertThat(payloadOf("orders/created/X1"))
                .isEqualTo("second-payload");

        ReplayService.Decision d = replayService.process(
                replayCommand("orders/created/X1"));
        assertThat(d.success()).isTrue();
        assertThat(d.destination())
                .isEqualTo("orders/created/X1/compacted");
        assertThat(new String(d.payload(), StandardCharsets.UTF_8))
                .isEqualTo("second-payload");
    }

    @Test
    void bulkReplayFannedOutAcrossPersistedRecords() {
        for (int i = 0; i < 50; i++) {
            compactionService.compact(messageOnTopic(
                    "orders/created/" + i, "payload-" + i));
        }
        assertThat(countKeys("orders/created/")).isEqualTo(50);

        BulkReplayService.BulkResult result = bulkReplayService.execute(
                new CommandEvent(CommandType.BULK_REPLAY, null,
                        "orders/created/*", Map.of()));

        assertThat(result.matched()).isEqualTo(50);
        assertThat(result.replayed()).isEqualTo(50);
        assertThat(sentMessages).hasSize(50);
    }

    @Test
    void deleteCascadeRemovesPersistedKeys() {
        for (String k : new String[]{"a", "b", "c"}) {
            compactionService.compact(messageOnTopic(
                    "orders/created/" + k, "payload-" + k));
        }
        compactionService.compact(messageOnTopic(
                "invoices/X", "keep-me"));
        assertThat(countKeys("orders/created/")).isEqualTo(3);
        assertThat(kvStore.get("invoices/X")).isPresent();

        DeleteCommandService.DeleteResult result = deleteService.execute(
                new CommandEvent(CommandType.DELETE,
                        "orders/created/a", null,
                        Map.of("cascade", "orders/created/*")));

        assertThat(result.cascadeDeleted()).isEqualTo(3);
        assertThat(countKeys("orders/created/")).isZero();
        assertThat(kvStore.get("invoices/X")).isPresent();
    }

    @Test
    void retentionEvictionRemovesAgedRecords() {
        long now = clock.instant().toEpochMilli();
        kvStore.put("orders/old", new CompactedRecord(
                "p".getBytes(StandardCharsets.UTF_8), Map.of(),
                "orders/old", now - Duration.ofHours(2).toMillis(),
                null));
        kvStore.put("orders/young", new CompactedRecord(
                "p".getBytes(StandardCharsets.UTF_8), Map.of(),
                "orders/young", now - Duration.ofMinutes(5).toMillis(),
                null));

        RetentionProperties p = new RetentionProperties();
        p.setDefaultTtl(Duration.ofHours(1));
        // Reach into the service's collaborator via reflection-free
        // re-construction with the desired props.
        RetentionService svc = new RetentionService(
                kvStore, p, metrics, clock);
        int evicted = svc.sweep();

        assertThat(evicted).isEqualTo(1);
        assertThat(kvStore.get("orders/old")).isEmpty();
        assertThat(kvStore.get("orders/young")).isPresent();
    }

    @Test
    void backupRestoreRoundtripPreservesAllRecords() throws Exception {
        for (int i = 0; i < 20; i++) {
            compactionService.compact(messageOnTopic(
                    "orders/x" + i, "payload-" + i));
        }
        assertThat(countKeys("orders/")).isEqualTo(20);

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        backupService.backup(out);

        // Wipe a few keys then restore - the restore should put
        // them back.
        kvStore.delete("orders/x5");
        kvStore.delete("orders/x10");
        assertThat(kvStore.get("orders/x5")).isEmpty();

        backupService.restore(
                new ByteArrayInputStream(out.toByteArray()));

        assertThat(countKeys("orders/")).isEqualTo(20);
        assertThat(payloadOf("orders/x5")).isEqualTo("payload-5");
        assertThat(payloadOf("orders/x10")).isEqualTo("payload-10");
    }

    @Test
    void persistenceAcrossKvStoreReopen() {
        compactionService.compact(messageOnTopic(
                "orders/persistent", "before-restart"));
        assertThat(payloadOf("orders/persistent"))
                .isEqualTo("before-restart");

        // Close + re-open the store, simulating a pod restart.
        kvStore.close();
        kvStore = new RocksDbKvStore(makeKvProps(tempDir));
        kvStore.open();

        assertThat(payloadOf("orders/persistent"))
                .isEqualTo("before-restart");
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    private static KvStoreProperties makeKvProps(Path tempDir) {
        KvStoreProperties p = new KvStoreProperties();
        p.getRocksdb().setPath(tempDir.resolve("rocksdb").toString());
        return p;
    }

    private Message<?> messageOnTopic(String topic, String body) {
        return new GenericMessage<>(
                body.getBytes(StandardCharsets.UTF_8),
                Map.of(
                        CompactionService.SOLACE_DESTINATION_HEADER,
                        topic));
    }

    private byte[] replayCommand(String key) {
        return ("{\"command\":\"REPLAY\",\"key\":\"" + key + "\"}")
                .getBytes(StandardCharsets.UTF_8);
    }

    private String payloadOf(String key) {
        return new String(kvStore.get(key).orElseThrow().payload(),
                StandardCharsets.UTF_8);
    }

    private long countKeys(String prefix) {
        try (var s = kvStore.keys(prefix)) {
            return s.count();
        }
    }

    private static final class MutableClock extends Clock {
        private long nowMillis;

        MutableClock(long nowMillis) {
            this.nowMillis = nowMillis;
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return Instant.ofEpochMilli(nowMillis);
        }
    }
}
