package com.solace.labs.mi.topiccompaction.lookup;

import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.observation.annotation.Observed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageHeaders;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Resolves the key for a Solace lookup request and returns the stored record
 * (or a "not found" response).
 *
 * <p>The MI supports two key-source conventions for flexibility:
 * <ol>
 *   <li><b>Header-based</b> - client sets {@code x-compaction-key} user property
 *       on the request. Most reliable across clients.</li>
 *   <li><b>Topic-tail</b> - client publishes to a topic like
 *       {@code compacted/lookup/orders/12345}. The MI strips the configured
 *       prefix to recover the key. Useful for HTTP/REST gateways that publish
 *       via topic.</li>
 * </ol>
 */
@Service
public class LookupService {

    private static final Logger log = LoggerFactory.getLogger(LookupService.class);

    private static final String NOT_FOUND_PAYLOAD =
            "{\"status\":\"not-found\"}";

    private final KvStore kvStore;
    private final LookupProperties properties;
    private final CompactionMetrics metrics;

    public LookupService(KvStore kvStore, LookupProperties properties, CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.properties = properties;
        this.metrics = metrics;
    }

    @Observed(name = "lookup.resolve",
            contextualName = "lookup-request",
            lowCardinalityKeyValues = {"workflow", "lookup"})
    public Result resolve(Message<?> request) {
        try (MDC.MDCCloseable ignored = MDC.putCloseable(
                "service", "lookup")) {
            metrics.recordLookup();
            MessageHeaders headers = request.getHeaders();
            String key = extractKey(headers);
            if (key == null || key.isBlank()) {
                return Result.notFound(
                        "Lookup request missing key: set header '"
                        + properties.getKeyHeader() + "' or publish to '"
                        + properties.getTopicKeyPrefix() + "<key>' topic");
            }

            try (MDC.MDCCloseable ignoredKey = MDC.putCloseable(
                    "key", key)) {
                Optional<CompactedRecord> record = kvStore.get(key);
                if (record.isEmpty()) {
                    metrics.recordLookupMiss();
                    log.debug("Lookup miss: key={}", key);
                    return Result.notFound(
                            "No record stored for key: " + key);
                }

                log.debug("Lookup hit: key={} ({} bytes)",
                        key, record.get().payload().length);
                Map<String, Object> responseHeaders =
                        new LinkedHashMap<>(record.get().headers());
                responseHeaders.put("x-compaction-key", key);
                responseHeaders.put("x-compaction-status", "found");
                return Result.found(
                        record.get().payload(), responseHeaders);
            }
        }
    }

    String extractKey(MessageHeaders headers) {
        Object headerKey = headers.get(properties.getKeyHeader());
        if (headerKey != null && !headerKey.toString().isBlank()) {
            return headerKey.toString();
        }
        if (properties.getTopicKeyPrefix() != null && !properties.getTopicKeyPrefix().isBlank()) {
            Object destination = headers.get("solace_destination");
            if (destination != null) {
                String topic = destination.toString();
                String prefix = properties.getTopicKeyPrefix();
                if (topic.startsWith(prefix)) {
                    return topic.substring(prefix.length());
                }
            }
        }
        return null;
    }

    /**
     * The result of a lookup, ready to be turned into a Solace reply.
     */
    public record Result(boolean found, byte[] payload, Map<String, Object> headers) {
        public static Result found(byte[] payload, Map<String, Object> headers) {
            return new Result(true, payload, headers);
        }

        public static Result notFound(String reason) {
            Map<String, Object> headers = new LinkedHashMap<>();
            headers.put("x-compaction-status", "not-found");
            headers.put("x-compaction-reason", reason);
            headers.put("content-type", "application/json");
            return new Result(false, NOT_FOUND_PAYLOAD.getBytes(StandardCharsets.UTF_8), headers);
        }
    }
}
