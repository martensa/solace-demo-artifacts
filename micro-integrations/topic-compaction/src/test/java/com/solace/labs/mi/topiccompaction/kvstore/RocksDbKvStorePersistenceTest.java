package com.solace.labs.mi.topiccompaction.kvstore;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * RocksDB-specific test: data must survive a close/re-open cycle.
 */
class RocksDbKvStorePersistenceTest {

    @Test
    void dataSurvivesRestart(@TempDir Path tempDir) {
        KvStoreProperties props = new KvStoreProperties();
        props.getRocksdb().setPath(tempDir.toString());

        // First open: write a value
        RocksDbKvStore first = new RocksDbKvStore(props);
        first.open();
        try {
            first.put("orders/created/1", new CompactedRecord(
                    "persisted".getBytes(StandardCharsets.UTF_8),
                    Map.of("solace_destination", "orders/created/1"),
                    "orders/created/1",
                    100L,
                    null));
        } finally {
            first.close();
        }

        // Second open: read it back
        RocksDbKvStore second = new RocksDbKvStore(props);
        second.open();
        try {
            Optional<CompactedRecord> retrieved = second.get("orders/created/1");
            assertThat(retrieved).isPresent();
            assertThat(new String(retrieved.get().payload(), StandardCharsets.UTF_8))
                    .isEqualTo("persisted");
        } finally {
            second.close();
        }
    }
}
