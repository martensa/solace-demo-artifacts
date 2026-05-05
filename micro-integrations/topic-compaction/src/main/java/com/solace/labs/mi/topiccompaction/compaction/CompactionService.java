package com.solace.labs.mi.topiccompaction.compaction;

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
 * Pure compaction logic - extract topic + payload from a Solace message and
 * write the latest version to the KV store.
 *
 * <p>Stateless and thread-safe; backed by injected {@link KvStore}.
 *
 * <p>The {@link Result} explains what happened. The interceptor uses it to
 * decide what audit event to emit (or whether to drop the message entirely).
 */
@Service
public class CompactionService {

    private static final Logger log = LoggerFactory.getLogger(CompactionService.class);

    /** Solace user-property header carrying the destination of the inbound message. */
    public static final String SOLACE_DESTINATION_HEADER = "solace_destination";

    private final KvStore kvStore;
    private final CompactionProperties properties;
    private final CompactionMetrics metrics;

    public CompactionService(KvStore kvStore, CompactionProperties properties, CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.properties = properties;
        this.metrics = metrics;
    }

    /**
     * Run the compaction step on a single inbound message.
     *
     * <p>The {@link Observed} annotation creates a span named
     * {@code compaction.process} via the Micrometer Tracing bridge,
     * and an MDC entry named {@code service=compaction} is attached
     * for the duration of the call so log lines emitted from inside
     * carry the workflow context.
     *
     * @return the outcome - the caller (interceptor) uses this to populate the
     *         audit event or skip emission entirely.
     */
    @Observed(name = "compaction.process",
            contextualName = "compact-message",
            lowCardinalityKeyValues = {"workflow", "compaction"})
    public Result compact(Message<?> message) {
        try (MDC.MDCCloseable ignored1 = MDC.putCloseable(
                "service", "compaction")) {
            return doCompact(message);
        }
    }

    private Result doCompact(Message<?> message) {
        MessageHeaders headers = message.getHeaders();

        // 1) Loop protection - if this message itself was a replay, do not re-store.
        String loopHeader = properties.getLoopProtectionHeader();
        if (loopHeader != null && !loopHeader.isBlank()) {
            Object loopFlag = headers.get(loopHeader);
            if (isTrue(loopFlag)) {
                metrics.recordLoopSkip();
                log.debug("Skipping compaction: message has loop-protection header {}={}", loopHeader, loopFlag);
                return new Result(Outcome.SKIPPED_LOOP, null, null);
            }
        }

        // 2) Topic extraction - the Solace binder injects solace_destination.
        String topic = stringHeader(headers, SOLACE_DESTINATION_HEADER);
        if (topic == null || topic.isBlank()) {
            log.warn("Skipping compaction: missing {} header on inbound message", SOLACE_DESTINATION_HEADER);
            return new Result(Outcome.SKIPPED_NO_TOPIC, null, null);
        }

        // 3) Optional sender-timestamp ordering check.
        Long senderTs = null;
        if (properties.getOrdering().enabled()) {
            senderTs = parseLongHeader(headers, properties.getOrdering().getHeader());
            if (senderTs != null) {
                Optional<CompactedRecord> existing = kvStore.get(topic);
                if (existing.isPresent() && existing.get().senderTimestamp() != null
                        && existing.get().senderTimestamp() > senderTs) {
                    metrics.recordOutOfOrderSkip();
                    log.debug("Skipping compaction: out-of-order. topic={}, existingTs={}, incomingTs={}",
                            topic, existing.get().senderTimestamp(), senderTs);
                    return new Result(Outcome.SKIPPED_OUT_OF_ORDER, topic, null);
                }
            }
        }

        // 4) Build and store the record.
        byte[] payload = payloadAsBytes(message.getPayload());
        Map<String, Object> headerCopy = filterAndCopy(headers);
        CompactedRecord record = new CompactedRecord(
                payload,
                headerCopy,
                topic,
                System.currentTimeMillis(),
                senderTs);
        kvStore.put(topic, record);
        metrics.recordUpsert();
        log.debug("Compacted topic={} ({} bytes)", topic, payload.length);
        return new Result(Outcome.UPSERTED, topic, record);
    }

    private static byte[] payloadAsBytes(Object payload) {
        if (payload instanceof byte[] b) return b;
        if (payload instanceof String s) return s.getBytes(StandardCharsets.UTF_8);
        // Fall back to toString() - not perfect but keeps the MI alive.
        return String.valueOf(payload).getBytes(StandardCharsets.UTF_8);
    }

    private static Map<String, Object> filterAndCopy(MessageHeaders headers) {
        // Drop the framework-only id/timestamp - those would conflict on replay.
        Map<String, Object> out = new LinkedHashMap<>(headers.size());
        for (Map.Entry<String, Object> e : headers.entrySet()) {
            String k = e.getKey();
            if ("id".equals(k) || "timestamp".equals(k) || "deliveryAttempt".equals(k)) continue;
            if (k.startsWith("scst_")) continue; // Spring Cloud Stream internals
            out.put(k, e.getValue());
        }
        return out;
    }

    private static String stringHeader(MessageHeaders headers, String key) {
        Object value = headers.get(key);
        return value == null ? null : value.toString();
    }

    private static Long parseLongHeader(MessageHeaders headers, String key) {
        Object value = headers.get(key);
        if (value instanceof Number n) return n.longValue();
        if (value instanceof String s) {
            try { return Long.parseLong(s.trim()); } catch (NumberFormatException ignore) { /* fallthrough */ }
        }
        return null;
    }

    private static boolean isTrue(Object value) {
        if (value instanceof Boolean b) return b;
        if (value == null) return false;
        return "true".equalsIgnoreCase(value.toString());
    }

    /** Outcome of a single compaction call. */
    public enum Outcome {
        UPSERTED, SKIPPED_LOOP, SKIPPED_OUT_OF_ORDER, SKIPPED_NO_TOPIC
    }

    /**
     * @param outcome the outcome category
     * @param topic   the original topic (null for SKIPPED_LOOP / SKIPPED_NO_TOPIC)
     * @param record  the stored record (only for UPSERTED)
     */
    public record Result(Outcome outcome, String topic, CompactedRecord record) {
        public boolean isUpsert() { return outcome == Outcome.UPSERTED; }
    }
}
