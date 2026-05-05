package com.solace.labs.mi.topiccompaction.api;

import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * REST surface for direct lookups against the compacted KV store.
 *
 * <p>Endpoints (all under {@code /api/v1/kv}):
 * <ul>
 *   <li>{@code GET /{*key}} - return the latest record for the key.
 *       Default response is the raw payload bytes; pass
 *       {@code ?format=meta} for a JSON envelope with metadata and a
 *       base64-encoded payload.</li>
 *   <li>{@code DELETE /{*key}} - tombstone (remove the entry).</li>
 *   <li>{@code GET /} - list keys with prefix and pagination.</li>
 * </ul>
 *
 * <p>The {@code {*key}} pattern (Spring {@code PathPattern} style)
 * captures the entire remaining path including embedded slashes.
 * Examples:
 * <pre>
 *   GET    /api/v1/kv/orders/created/12345
 *   GET    /api/v1/kv/orders/created/12345?format=meta
 *   DELETE /api/v1/kv/orders/created/12345
 *   GET    /api/v1/kv?prefix=orders/&amp;limit=50
 * </pre>
 *
 * <p>Compared to the V0 MVP this controller no longer requires the
 * client to URL-encode slashes (the prior {@code {key}} mapping
 * combined with Spring's path decoding caused a 400 for keys that
 * contained {@code /}). The deprecated {@code /{key}/meta} sub-path
 * is replaced by the {@code ?format=meta} query parameter. See
 * {@code CHANGELOG.md} for the migration note.
 */
@RestController
@RequestMapping("/api/v1/kv")
public class KvStoreController {

    private static final String FORMAT_RAW = "raw";
    private static final String FORMAT_META = "meta";
    private static final int LIMIT_MIN = 1;
    private static final int LIMIT_MAX = 10_000;

    private final KvStore kvStore;
    private final CompactionMetrics metrics;

    public KvStoreController(KvStore kvStore, CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.metrics = metrics;
    }

    /**
     * Return the value stored for {@code key}.
     *
     * @param key    full key path captured from the URL; leading slash
     *               from the {@code {*key}} pattern is stripped here.
     * @param format {@code raw} (default) returns the payload bytes;
     *               {@code meta} returns a JSON metadata envelope.
     */
    @GetMapping("/{*key}")
    public ResponseEntity<?> get(
            @PathVariable String key,
            @RequestParam(required = false, defaultValue = FORMAT_RAW)
            String format) {
        validateFormat(format);
        String normalizedKey = normalizeKey(key);
        if (normalizedKey.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        metrics.recordLookup();
        Optional<CompactedRecord> record = kvStore.get(normalizedKey);
        if (record.isEmpty()) {
            metrics.recordLookupMiss();
            return ResponseEntity.notFound().build();
        }
        return FORMAT_META.equalsIgnoreCase(format)
                ? buildMetaResponse(normalizedKey, record.get())
                : buildRawResponse(record.get());
    }

    /**
     * Tombstone the record for {@code key}. Used as an admin operation
     * to forcibly evict known-bad state. The MI will repopulate the
     * record on the next inbound message for that topic.
     */
    @DeleteMapping("/{*key}")
    public ResponseEntity<Void> delete(@PathVariable String key) {
        String normalizedKey = normalizeKey(key);
        if (normalizedKey.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        kvStore.delete(normalizedKey);
        return ResponseEntity.noContent().build();
    }

    /**
     * List keys with optional prefix filter and pagination.
     *
     * @param prefix prefix to filter by; empty matches all keys
     * @param limit  page size, between 1 and 10000 inclusive
     */
    @GetMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> listKeys(
            @RequestParam(defaultValue = "") String prefix,
            @RequestParam(defaultValue = "100") int limit) {
        validateLimit(limit);
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

    private ResponseEntity<byte[]> buildRawResponse(CompactedRecord record) {
        HttpHeaders responseHeaders = new HttpHeaders();
        Object contentType = record.headers().get("content-type");
        responseHeaders.setContentType(MediaType.parseMediaType(
                contentType == null ? "application/octet-stream"
                        : contentType.toString()));
        responseHeaders.add("x-compacted-topic", record.originalTopic());
        responseHeaders.add("x-compacted-ingest-timestamp",
                String.valueOf(record.ingestTimestamp()));
        if (record.senderTimestamp() != null) {
            responseHeaders.add("x-compacted-sender-timestamp",
                    String.valueOf(record.senderTimestamp()));
        }
        return new ResponseEntity<>(record.payload(),
                responseHeaders, HttpStatus.OK);
    }

    private ResponseEntity<Map<String, Object>> buildMetaResponse(
            String key, CompactedRecord record) {
        Map<String, Object> response = new LinkedHashMap<>();
        response.put("key", key);
        response.put("topic", record.originalTopic());
        response.put("ingestTimestamp", record.ingestTimestamp());
        response.put("senderTimestamp", record.senderTimestamp());
        response.put("sizeBytes", record.sizeBytes());
        response.put("headers", record.headers());
        response.put("payloadBase64", Base64.getEncoder()
                .encodeToString(record.payload()));
        return ResponseEntity.ok(response);
    }

    /**
     * Normalize the captured path:
     * <ol>
     *   <li>strip the leading slash that the {@code {*key}} pattern
     *       includes (Spring {@code PathPattern} behaviour)</li>
     *   <li>URL-decode the remaining string so legacy clients that
     *       still encode {@code /} as {@code %2F} continue to work</li>
     * </ol>
     */
    private static String normalizeKey(String key) {
        if (key == null || key.isEmpty()) {
            return "";
        }
        String stripped = key.startsWith("/") ? key.substring(1) : key;
        return URLDecoder.decode(stripped, StandardCharsets.UTF_8);
    }

    private static void validateFormat(String format) {
        if (!FORMAT_RAW.equalsIgnoreCase(format)
                && !FORMAT_META.equalsIgnoreCase(format)) {
            throw new IllegalArgumentException(
                    "format must be 'raw' or 'meta'");
        }
    }

    private static void validateLimit(int limit) {
        if (limit < LIMIT_MIN || limit > LIMIT_MAX) {
            throw new IllegalArgumentException(
                    "limit must be between " + LIMIT_MIN
                            + " and " + LIMIT_MAX);
        }
    }
}
