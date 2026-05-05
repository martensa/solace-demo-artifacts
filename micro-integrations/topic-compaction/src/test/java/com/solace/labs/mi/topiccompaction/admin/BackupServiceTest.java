package com.solace.labs.mi.topiccompaction.admin;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class BackupServiceTest {

    private KvStore kvStore;
    private BackupService service;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        service = new BackupService(kvStore, new ObjectMapper());
    }

    @Test
    void roundtripsAllRecords() throws IOException {
        seed("orders/A", "alpha");
        seed("orders/B", "bravo");
        seed("invoices/X", "echo");

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        BackupService.BackupStats stats = service.backup(out);
        assertThat(stats.records()).isEqualTo(3);

        // Wipe the source and restore from the captured bytes.
        kvStore.delete("orders/A");
        kvStore.delete("orders/B");
        kvStore.delete("invoices/X");
        assertThat(kvStore.size()).isZero();

        BackupService.RestoreStats restoreStats = service.restore(
                new ByteArrayInputStream(out.toByteArray()));
        assertThat(restoreStats.restored()).isEqualTo(3);
        assertThat(restoreStats.skipped()).isZero();

        assertThat(kvStore.size()).isEqualTo(3);
        assertThat(payload(kvStore.get("orders/A"))).isEqualTo("alpha");
        assertThat(payload(kvStore.get("orders/B"))).isEqualTo("bravo");
        assertThat(payload(kvStore.get("invoices/X"))).isEqualTo("echo");
    }

    @Test
    void backupHeaderContainsCount() throws IOException {
        seed("k1", "v1");
        seed("k2", "v2");

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        service.backup(out);

        String first = new String(out.toByteArray(),
                StandardCharsets.UTF_8).split("\n")[0];
        @SuppressWarnings("unchecked")
        Map<String, Object> header = new ObjectMapper().readValue(
                first, Map.class);
        assertThat(header).containsEntry("version", 1)
                .containsEntry("recordCount", 2);
    }

    @Test
    void restoreWipesExistingRecords() throws IOException {
        seed("orders/A", "alpha");
        ByteArrayOutputStream backup = new ByteArrayOutputStream();
        service.backup(backup);

        // Add a key after the backup; restore should remove it.
        seed("orders/B", "bravo");
        assertThat(kvStore.size()).isEqualTo(2);

        BackupService.RestoreStats stats = service.restore(
                new ByteArrayInputStream(backup.toByteArray()));
        assertThat(stats.wiped()).isEqualTo(2);
        assertThat(stats.restored()).isEqualTo(1);
        assertThat(kvStore.get("orders/A")).isPresent();
        assertThat(kvStore.get("orders/B")).isEmpty();
    }

    @Test
    void preservesHeadersAndTimestamps() throws IOException {
        kvStore.put("k", new CompactedRecord(
                "p".getBytes(StandardCharsets.UTF_8),
                Map.of("custom-header", "value",
                        "content-type", "application/json"),
                "k", 12345L, 67890L));

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        service.backup(out);

        kvStore.delete("k");
        service.restore(
                new ByteArrayInputStream(out.toByteArray()));

        CompactedRecord r = kvStore.get("k").orElseThrow();
        assertThat(r.ingestTimestamp()).isEqualTo(12345L);
        assertThat(r.senderTimestamp()).isEqualTo(67890L);
        assertThat(r.headers())
                .containsEntry("custom-header", "value")
                .containsEntry("content-type", "application/json");
    }

    @Test
    void rejectsRestoreFromEmptyStream() {
        assertThatThrownBy(() -> service.restore(
                new ByteArrayInputStream(new byte[0])))
                .isInstanceOf(IOException.class)
                .hasMessageContaining("Empty backup stream");
    }

    @Test
    void rejectsRestoreFromUnsupportedVersion() {
        String header = "{\"version\":999,\"recordCount\":0}\n";
        assertThatThrownBy(() -> service.restore(
                new ByteArrayInputStream(header.getBytes(
                        StandardCharsets.UTF_8))))
                .isInstanceOf(IOException.class)
                .hasMessageContaining(
                        "Unsupported backup format version");
    }

    @Test
    void skipsMalformedLines() throws IOException {
        seed("k1", "v1");
        ByteArrayOutputStream backup = new ByteArrayOutputStream();
        service.backup(backup);

        // Append a malformed line after the valid one.
        String tampered = new String(backup.toByteArray(),
                StandardCharsets.UTF_8) + "{ malformed\n";

        kvStore.delete("k1");
        BackupService.RestoreStats stats = service.restore(
                new ByteArrayInputStream(tampered.getBytes(
                        StandardCharsets.UTF_8)));
        assertThat(stats.restored()).isEqualTo(1);
        assertThat(stats.skipped()).isEqualTo(1);
    }

    private void seed(String key, String body) {
        kvStore.put(key, new CompactedRecord(
                body.getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", key),
                key, System.currentTimeMillis(), null));
    }

    private static String payload(Optional<CompactedRecord> r) {
        return new String(r.orElseThrow().payload(),
                StandardCharsets.UTF_8);
    }
}
