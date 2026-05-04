package com.solace.labs.mi.topiccompaction.api;

import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * REST surface for direct lookups against the compacted KV store.
 *
 * <p>Endpoints:
 * <ul>
 *   <li>{@code GET /api/v1/kv/{key}} - return the latest compacted record for the key</li>
 *   <li>{@code GET /api/v1/kv?prefix=&limit=} - list keys with pagination</li>
 *   <li>{@code DELETE /api/v1/kv/{key}} - remove the entry (tombstone)</li>
 * </ul>
 *
 * <p>The path variable handles slashes: clients should URL-encode the key
 * (e.g. {@code orders%2Fcreated%2F12345}).
 */
@RestController
@RequestMapping("/api/v1/kv")
public class KvStoreController {

    private final KvStore kvStore;
    private final CompactionMetrics metrics;

    public KvStoreController(KvStore kvStore, CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.metrics = metrics;
    }

    /**
     * Return the binary payload of the latest compacted record for {@code key}.
     * Headers from the original message are returned as response headers
     * prefixed {@code x-compacted-header-}.
     */
    @GetMapping("/{key}")
    public ResponseEntity<byte[]> getRaw(@PathVariable String key) {
        metrics.recordLookup();
        Optional<CompactedRecord> record = kvStore.get(key);
        if (record.isEmpty()) {
            metrics.recordLookupMiss();
            return ResponseEntity.notFound().build();
        }
        HttpHeaders responseHeaders = new HttpHeaders();
        Object contentType = record.get().headers().get("content-type");
        responseHeaders.setContentType(MediaType.parseMediaType(
                contentType == null ? "application/octet-stream" : contentType.toString()));
        responseHeaders.add("x-compacted-topic", record.get().originalTopic());
        responseHeaders.add("x-compacted-ingest-timestamp",
                String.valueOf(record.get().ingestTimestamp()));
        if (record.get().senderTimestamp() != null) {
            responseHeaders.add("x-compacted-sender-timestamp",
                    String.valueOf(record.get().senderTimestamp()));
        }
        return new ResponseEntity<>(record.get().payload(), responseHeaders,
                org.springframework.http.HttpStatus.OK);
    }

    /**
     * Metadata-only lookup - returns the stored record as a JSON document with
     * a base64 payload.
     */
    @GetMapping(value = "/{key}/meta", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, Object>> getMeta(@PathVariable String key) {
        metrics.recordLookup();
        Optional<CompactedRecord> record = kvStore.get(key);
        if (record.isEmpty()) {
            metrics.recordLookupMiss();
            return ResponseEntity.notFound().build();
        }
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("key", key);
        response.put("topic", record.get().originalTopic());
        response.put("ingestTimestamp", record.get().ingestTimestamp());
        response.put("senderTimestamp", record.get().senderTimestamp());
        response.put("sizeBytes", record.get().sizeBytes());
        response.put("headers", record.get().headers());
        response.put("payloadBase64", java.util.Base64.getEncoder()
                .encodeToString(record.get().payload()));
        return ResponseEntity.ok(response);
    }

    /**
     * List keys, optionally filtered by prefix.
     */
    @GetMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> listKeys(@RequestParam(defaultValue = "") String prefix,
                                        @RequestParam(defaultValue = "100") int limit) {
        try (Stream<String> keys = kvStore.keys(prefix)) {
            List<String> matches = keys.limit(limit).toList();
            Map<String, Object> response = new LinkedHashMap<>();
            response.put("prefix", prefix);
            response.put("limit", limit);
            response.put("count", matches.size());
            response.put("keys", matches);
            response.put("storeSize", kvStore.size());
            return response;
        }
    }

    /**
     * Tombstone the record for {@code key}. Used as an admin operation to
     * forcibly evict known-bad state. The MI will repopulate the record on the
     * next inbound message for that topic.
     */
    @DeleteMapping("/{key}")
    public ResponseEntity<Void> delete(@PathVariable String key) {
        kvStore.delete(key);
        return ResponseEntity.noContent().build();
    }
}
