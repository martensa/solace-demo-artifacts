package com.solace.labs.mi.topiccompaction.retention;

import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.observation.annotation.Observed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import java.util.stream.Stream;

/**
 * Background sweeper that evicts records past their TTL.
 *
 * <p>Activated by {@code topic-compaction.retention.enabled = true}.
 * Runs on a fixed delay (default 5 minutes) and iterates the entire
 * KV store; per record, looks up the applicable TTL via
 * {@link RetentionProperties#resolveTtl(String)} and evicts if
 * {@code ingestTimestamp + ttl < now}.
 *
 * <p>Iteration is streaming (no full snapshot in memory) so it works
 * for stores in the millions of keys.
 */
@Component
@ConditionalOnProperty(prefix = "topic-compaction.retention",
        name = "enabled", havingValue = "true")
public class RetentionService {

    private static final Logger log =
            LoggerFactory.getLogger(RetentionService.class);

    private final KvStore kvStore;
    private final RetentionProperties properties;
    private final CompactionMetrics metrics;
    private final Clock clock;

    public RetentionService(KvStore kvStore,
                            RetentionProperties properties,
                            CompactionMetrics metrics,
                            Clock clock) {
        this.kvStore = kvStore;
        this.properties = properties;
        this.metrics = metrics;
        this.clock = clock;
    }

    /**
     * Public entry point so tests can call the sweep directly.
     * Returns the number of records evicted.
     */
    @Observed(name = "retention.sweep",
            contextualName = "retention-sweep",
            lowCardinalityKeyValues = {"workflow", "retention"})
    public int sweep() {
        long now = clock.instant().toEpochMilli();
        int scanned = 0;
        int evicted = 0;
        try (Stream<String> keys = kvStore.keys("")) {
            for (String key : (Iterable<String>) keys::iterator) {
                scanned++;
                if (shouldEvict(key, now)) {
                    try {
                        kvStore.delete(key);
                        evicted++;
                        metrics.recordRetentionEviction();
                    } catch (Exception e) {
                        log.error("Retention: failed to evict "
                                + "key={}", key, e);
                    }
                }
            }
        }
        if (evicted > 0) {
            log.info("Retention: scanned={} evicted={}",
                    scanned, evicted);
        } else {
            log.debug("Retention: scanned={} evicted=0", scanned);
        }
        return evicted;
    }

    private boolean shouldEvict(String key, long nowMillis) {
        Duration ttl = properties.resolveTtl(key);
        if (ttl == null) {
            return false;  // null TTL = keep forever
        }
        Optional<CompactedRecord> rec = kvStore.get(key);
        if (rec.isEmpty()) {
            return false;  // concurrent eviction
        }
        Instant ingestedAt = Instant.ofEpochMilli(
                rec.get().ingestTimestamp());
        Instant deadline = ingestedAt.plus(ttl);
        return deadline.toEpochMilli() < nowMillis;
    }

    /**
     * Spring scheduling entry point. Configured via
     * {@link RetentionProperties#getCheckInterval()} expressed in
     * milliseconds via SpEL.
     */
    @Scheduled(fixedDelayString =
            "#{@retentionProperties.checkInterval.toMillis()}",
            initialDelayString =
            "#{@retentionProperties.checkInterval.toMillis()}")
    public void scheduledSweep() {
        sweep();
    }

    /**
     * Wires the retention configuration so {@link RetentionService}
     * can be enabled by property.
     */
    @Configuration
    @EnableConfigurationProperties(RetentionProperties.class)
    @EnableScheduling
    @ConditionalOnProperty(prefix = "topic-compaction.retention",
            name = "enabled", havingValue = "true")
    public static class RetentionAutoConfiguration {

        @org.springframework.context.annotation.Bean
        @org.springframework.boot.autoconfigure.condition
                .ConditionalOnMissingBean
        public Clock retentionClock() {
            return Clock.systemUTC();
        }
    }
}
