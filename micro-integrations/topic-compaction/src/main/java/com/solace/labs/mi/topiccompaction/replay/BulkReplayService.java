package com.solace.labs.mi.topiccompaction.replay;

import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.micrometer.observation.annotation.Observed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.cloud.stream.binder.BinderHeaders;
import org.springframework.cloud.stream.function.StreamBridge;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * Executes the {@link com.solace.labs.mi.topiccompaction.command.CommandType
 * #BULK_REPLAY} command. Iterates the KV store using a
 * {@link SolacePatternMatcher} and republishes the latest record for
 * every match. Throughput is capped by an optional client-supplied
 * rate limit.
 *
 * <p>Each replay message is sent via {@link StreamBridge} to the
 * dedicated {@code bulk-replay-fanout} binding (output-3). That
 * binding has no producer interceptor, so the message is published
 * verbatim to the destination set in its headers.
 *
 * <p>The summary of a bulk replay (matched / replayed / failed
 * counts plus duration) is returned to the caller; the
 * {@link com.solace.labs.mi.topiccompaction.replay
 * .ReplayProducerInterceptorFactory replay interceptor} turns it
 * into the response message published on
 * {@code topic-compaction/replay/bulk-result}.
 *
 * <p>Loop protection: every fanout message carries the configured
 * loop-protection header so {@code CompactionService} skips
 * re-storing it.
 */
@Service
public class BulkReplayService {

    private static final Logger log =
            LoggerFactory.getLogger(BulkReplayService.class);

    /**
     * Spring Cloud Stream binding used for fanout. Reuses the
     * pre-registered {@code output-3} binding, configured in
     * {@code mi-config/application.yml} with a placeholder
     * destination (per-message destination is set via the
     * {@code solace_destination} header).
     */
    public static final String FANOUT_BINDING = "output-3";

    /** Default rate limit if the command does not override. */
    public static final int DEFAULT_RATE_LIMIT_PER_SEC = 1_000;

    private final KvStore kvStore;
    private final ReplayProperties properties;
    private final StreamBridge streamBridge;
    private final CompactionMetrics metrics;

    public BulkReplayService(KvStore kvStore,
                             ReplayProperties properties,
                             StreamBridge streamBridge,
                             CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.properties = properties;
        this.streamBridge = streamBridge;
        this.metrics = metrics;
    }

    @Observed(name = "replay.bulk",
            contextualName = "bulk-replay",
            lowCardinalityKeyValues = {"workflow", "bulk-replay"})
    public BulkResult execute(CommandEvent event) {
        try (MDC.MDCCloseable ignored = MDC.putCloseable(
                "service", "bulk-replay");
             MDC.MDCCloseable ignoredPattern = MDC.putCloseable(
                "pattern", event.pattern() == null ? ""
                        : event.pattern())) {
            return executeInternal(event);
        }
    }

    private BulkResult executeInternal(CommandEvent event) {
        if (event.pattern() == null || event.pattern().isBlank()) {
            return BulkResult.failed(event.pattern(),
                    "BULK_REPLAY pattern is required");
        }

        SolacePatternMatcher matcher;
        try {
            matcher = new SolacePatternMatcher(event.pattern());
        } catch (IllegalArgumentException e) {
            return BulkResult.failed(event.pattern(),
                    "Invalid pattern: " + e.getMessage());
        }

        int rateLimit = Math.max(1, event.intOption(
                "rateLimit", DEFAULT_RATE_LIMIT_PER_SEC));
        Bucket bucket = Bucket.builder()
                .addLimit(Bandwidth.builder()
                        .capacity(rateLimit)
                        .refillIntervally(rateLimit, Duration.ofSeconds(1))
                        .build())
                .build();

        long start = System.currentTimeMillis();
        int matched = 0;
        int replayed = 0;
        int failed = 0;

        log.info("BulkReplay: starting for pattern={} rateLimit={}/s",
                event.pattern(), rateLimit);
        try (Stream<String> keys =
                     kvStore.keys(matcher.prefixForRocksDb())) {
            for (String key : (Iterable<String>) keys
                    .filter(matcher::matches)::iterator) {
                matched++;
                try {
                    Optional<CompactedRecord> rec = kvStore.get(key);
                    if (rec.isEmpty()) {
                        // Concurrent eviction between filter and
                        // fetch - rare but possible.
                        failed++;
                        continue;
                    }
                    bucket.asBlocking().consume(1);
                    Message<byte[]> msg = buildReplayMessage(
                            key, rec.get(), event);
                    streamBridge.send(FANOUT_BINDING, msg);
                    replayed++;
                    metrics.recordReplay();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    log.warn("BulkReplay: interrupted; aborting "
                            + "after matched={}", matched);
                    break;
                } catch (Exception e) {
                    failed++;
                    log.error("BulkReplay: failed to publish "
                            + "key={}", key, e);
                }
            }
        }

        long durationMs = System.currentTimeMillis() - start;
        BulkResult result = new BulkResult(
                event.pattern(), matched, replayed, failed,
                durationMs, null);
        log.info("BulkReplay: done {}", result);
        return result;
    }

    private Message<byte[]> buildReplayMessage(
            String key, CompactedRecord record, CommandEvent event) {
        String suffix = event.stringOption("destinationSuffix",
                properties.getTargetSuffix());
        String destination = key + suffix;
        boolean includeHeaders = event.booleanOption(
                "includeOriginalHeaders", true);
        String correlationId = event.stringOption(
                "correlationId", null);

        MessageBuilder<byte[]> b = MessageBuilder
                .withPayload(record.payload());
        if (includeHeaders) {
            record.headers().forEach((k, v) -> {
                if (v != null) {
                    b.setHeader(k, v);
                }
            });
        }
        b.setHeader("solace_destination", destination);
        b.setHeader(BinderHeaders.TARGET_DESTINATION, destination);
        b.setHeader(properties.getLoopProtectionHeader(), true);
        b.setHeader("x-compaction-replay-source-key", key);
        b.setHeader("x-bulk-replay", true);
        if (correlationId != null) {
            b.setHeader("x-original-correlation-id", correlationId);
        }
        return b.build();
    }

    /**
     * Outcome of one bulk-replay execution. Sent back to the
     * interceptor which serialises it as a JSON message on the
     * bulk-result topic.
     */
    public record BulkResult(
            String pattern,
            int matched,
            int replayed,
            int failed,
            long durationMs,
            String error) {

        public boolean isSuccess() {
            return error == null;
        }

        public static BulkResult failed(String pattern, String error) {
            return new BulkResult(pattern, 0, 0, 0, 0L, error);
        }
    }
}
