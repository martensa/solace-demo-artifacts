package com.solace.labs.mi.topiccompaction.kvstore;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Contract test that runs against every {@link KvStore} implementation.
 * Ensures both backends behave identically for the operations the MI relies on.
 */
class KvStoreContractTest {

    @TempDir
    Path tempDir;

    private KvStore store;
    private RocksDbKvStore rocksDbStore; // kept for explicit close

    enum Backend { ROCKSDB, CAFFEINE }

    void setUp(Backend backend) {
        KvStoreProperties properties = new KvStoreProperties();
        switch (backend) {
            case ROCKSDB -> {
                properties.setBackend(KvStoreProperties.Backend.rocksdb);
                properties.getRocksdb().setPath(tempDir.toString());
                rocksDbStore = new RocksDbKvStore(properties);
                rocksDbStore.open();
                store = rocksDbStore;
            }
            case CAFFEINE -> {
                properties.setBackend(KvStoreProperties.Backend.caffeine);
                store = new CaffeineKvStore(properties);
            }
        }
    }

    @AfterEach
    void tearDown() {
        if (rocksDbStore != null) {
            rocksDbStore.close();
            rocksDbStore = null;
        }
        store = null;
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void getReturnsEmptyWhenKeyAbsent(Backend backend) {
        setUp(backend);
        assertThat(store.get("nope")).isEmpty();
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void putAndGetRoundTrip(Backend backend) {
        setUp(backend);
        CompactedRecord record = sampleRecord("orders/created/12345", "hello");
        store.put("orders/created/12345", record);

        Optional<CompactedRecord> retrieved = store.get("orders/created/12345");
        assertThat(retrieved).isPresent();
        assertThat(new String(retrieved.get().payload(), StandardCharsets.UTF_8)).isEqualTo("hello");
        assertThat(retrieved.get().originalTopic()).isEqualTo("orders/created/12345");
        assertThat(retrieved.get().headers()).containsEntry("solace_destination", "orders/created/12345");
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void putReplacesExistingValue(Backend backend) {
        setUp(backend);
        store.put("k1", sampleRecord("k1", "v1"));
        store.put("k1", sampleRecord("k1", "v2"));

        assertThat(new String(store.get("k1").orElseThrow().payload(), StandardCharsets.UTF_8))
                .isEqualTo("v2");
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void deleteRemovesKey(Backend backend) {
        setUp(backend);
        store.put("k1", sampleRecord("k1", "v1"));
        store.delete("k1");
        assertThat(store.get("k1")).isEmpty();
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void keysWithPrefixFilters(Backend backend) {
        setUp(backend);
        store.put("orders/created/1", sampleRecord("orders/created/1", "x"));
        store.put("orders/created/2", sampleRecord("orders/created/2", "x"));
        store.put("invoices/issued/1", sampleRecord("invoices/issued/1", "x"));

        try (Stream<String> keys = store.keys("orders/")) {
            List<String> matching = keys.toList();
            assertThat(matching).containsExactlyInAnyOrder("orders/created/1", "orders/created/2");
        }
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void preservesAllHeaderTypes(Backend backend) {
        setUp(backend);
        Map<String, Object> headers = new java.util.LinkedHashMap<>();
        headers.put("string-h", "value");
        headers.put("long-h", 42L);
        headers.put("int-h", 7);
        headers.put("bool-h", true);
        headers.put("bytes-h", new byte[]{1, 2, 3});
        CompactedRecord record = new CompactedRecord(
                "payload".getBytes(StandardCharsets.UTF_8),
                headers,
                "k1",
                System.currentTimeMillis(),
                null);

        store.put("k1", record);
        CompactedRecord roundTripped = store.get("k1").orElseThrow();

        assertThat(roundTripped.headers().get("string-h")).isEqualTo("value");
        assertThat(roundTripped.headers().get("long-h")).isEqualTo(42L);
        assertThat(roundTripped.headers().get("int-h")).isEqualTo(7);
        assertThat(roundTripped.headers().get("bool-h")).isEqualTo(true);
        assertThat((byte[]) roundTripped.headers().get("bytes-h")).containsExactly(1, 2, 3);
    }

    @ParameterizedTest
    @EnumSource(Backend.class)
    void preservesSenderTimestampWhenSet(Backend backend) {
        setUp(backend);
        CompactedRecord record = new CompactedRecord(
                "x".getBytes(StandardCharsets.UTF_8),
                Map.of(),
                "k1",
                100L,
                500L);
        store.put("k1", record);
        assertThat(store.get("k1").orElseThrow().senderTimestamp()).isEqualTo(500L);
    }

    private static CompactedRecord sampleRecord(String topic, String body) {
        return new CompactedRecord(
                body.getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", topic, "content-type", "text/plain"),
                topic,
                System.currentTimeMillis(),
                null);
    }
}
