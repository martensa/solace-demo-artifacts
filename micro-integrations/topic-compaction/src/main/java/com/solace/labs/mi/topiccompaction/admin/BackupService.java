package com.solace.labs.mi.topiccompaction.admin;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import io.micrometer.observation.annotation.Observed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Stream;

/**
 * Streaming backup and restore for the KV store.
 *
 * <p>Format: line-delimited JSON. The first line is a header
 * describing the snapshot:
 *
 * <pre>
 *   {"version":1,"backupTimestamp":1700000000000,"recordCount":3}
 *   {"key":"orders/A","payloadBase64":"...","headers":{...},
 *    "originalTopic":"orders/A","ingestTimestamp":...,
 *    "senderTimestamp":null}
 *   {"key":"orders/B",...}
 *   ...
 * </pre>
 *
 * <p>Restore iterates the input line-by-line; each record is
 * upserted into the store. The destination store is wiped first to
 * guarantee a clean restore. Concurrent writers are not blocked, so
 * for production restores the operator should ensure no inbound
 * traffic is reaching the MI.
 *
 * <p>Both directions are streaming, so the memory footprint is
 * O(one record) regardless of store size.
 */
@Service
public class BackupService {

    private static final Logger log =
            LoggerFactory.getLogger(BackupService.class);

    /** Backup format version. Bump if the schema changes. */
    public static final int FORMAT_VERSION = 1;

    private final KvStore kvStore;
    private final ObjectMapper objectMapper;

    public BackupService(KvStore kvStore, ObjectMapper objectMapper) {
        this.kvStore = kvStore;
        this.objectMapper = objectMapper;
    }

    /**
     * Stream the entire KV store as line-delimited JSON to
     * {@code out}. The output is flushed at the end; the caller is
     * responsible for closing the stream.
     */
    @Observed(name = "admin.backup",
            contextualName = "backup-stream",
            lowCardinalityKeyValues = {"workflow", "admin"})
    public BackupStats backup(OutputStream out) throws IOException {
        long start = System.currentTimeMillis();
        AtomicLong written = new AtomicLong();

        try (Writer w = new OutputStreamWriter(
                out, StandardCharsets.UTF_8)) {
            // Header line first - readers can use it to validate
            // format compatibility before processing records.
            Map<String, Object> header = new LinkedHashMap<>();
            header.put("version", FORMAT_VERSION);
            header.put("backupTimestamp",
                    System.currentTimeMillis());
            header.put("recordCount", kvStore.size());
            w.write(objectMapper.writeValueAsString(header));
            w.write('\n');

            try (Stream<String> keys = kvStore.keys("")) {
                for (String key : (Iterable<String>) keys::iterator) {
                    Optional<CompactedRecord> rec = kvStore.get(key);
                    if (rec.isEmpty()) {
                        // Concurrent eviction - skip
                        continue;
                    }
                    Map<String, Object> line =
                            recordToMap(key, rec.get());
                    w.write(objectMapper.writeValueAsString(line));
                    w.write('\n');
                    written.incrementAndGet();
                }
            }
            w.flush();
        }

        long durationMs = System.currentTimeMillis() - start;
        log.info("Backup: streamed {} records in {} ms",
                written.get(), durationMs);
        return new BackupStats(written.get(), durationMs);
    }

    /**
     * Restore the KV store from a line-delimited JSON stream.
     * Existing keys are wiped before the load; partial failure
     * leaves the store in an inconsistent state.
     */
    @Observed(name = "admin.restore",
            contextualName = "restore-stream",
            lowCardinalityKeyValues = {"workflow", "admin"})
    public RestoreStats restore(InputStream in) throws IOException {
        long start = System.currentTimeMillis();

        // Wipe first.
        long wiped = 0;
        try (Stream<String> keys = kvStore.keys("")) {
            for (String key : (Iterable<String>) keys::iterator) {
                kvStore.delete(key);
                wiped++;
            }
        }
        log.info("Restore: wiped {} existing records", wiped);

        long restored = 0;
        long skipped = 0;
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(in, StandardCharsets.UTF_8))) {
            String headerLine = reader.readLine();
            if (headerLine == null) {
                throw new IOException(
                        "Empty backup stream (no header line)");
            }
            Map<String, Object> header = objectMapper.readValue(
                    headerLine, Map.class);
            Object versionObj = header.get("version");
            if (!(versionObj instanceof Number)
                    || ((Number) versionObj).intValue()
                        != FORMAT_VERSION) {
                throw new IOException(
                        "Unsupported backup format version: "
                                + versionObj);
            }

            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                try {
                    Map<String, Object> rec = objectMapper.readValue(
                            line, Map.class);
                    String key = (String) rec.get("key");
                    if (key == null) {
                        skipped++;
                        continue;
                    }
                    kvStore.put(key, mapToRecord(rec));
                    restored++;
                } catch (Exception e) {
                    skipped++;
                    log.warn("Restore: skipping malformed line: {}",
                            e.getMessage());
                }
            }
        }

        long durationMs = System.currentTimeMillis() - start;
        log.info("Restore: wiped={} restored={} skipped={} ({} ms)",
                wiped, restored, skipped, durationMs);
        return new RestoreStats(wiped, restored, skipped, durationMs);
    }

    private Map<String, Object> recordToMap(
            String key, CompactedRecord record) {
        Map<String, Object> line = new LinkedHashMap<>();
        line.put("key", key);
        line.put("payloadBase64", Base64.getEncoder()
                .encodeToString(record.payload()));
        line.put("headers", record.headers());
        line.put("originalTopic", record.originalTopic());
        line.put("ingestTimestamp", record.ingestTimestamp());
        line.put("senderTimestamp", record.senderTimestamp());
        return line;
    }

    private CompactedRecord mapToRecord(Map<String, Object> rec) {
        byte[] payload = Base64.getDecoder().decode(
                (String) rec.get("payloadBase64"));
        @SuppressWarnings("unchecked")
        Map<String, Object> headers =
                (Map<String, Object>) rec.getOrDefault(
                        "headers", Map.of());
        String originalTopic = (String) rec.get("originalTopic");
        Long ingestTimestamp = ((Number) rec.get(
                "ingestTimestamp")).longValue();
        Object sentObj = rec.get("senderTimestamp");
        Long senderTimestamp = sentObj instanceof Number
                ? ((Number) sentObj).longValue() : null;
        return new CompactedRecord(payload, headers,
                originalTopic, ingestTimestamp, senderTimestamp);
    }

    public record BackupStats(long records, long durationMs) {}

    public record RestoreStats(long wiped, long restored,
                                long skipped, long durationMs) {}
}
