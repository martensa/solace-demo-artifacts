package com.solace.labs.mi.topiccompaction.retention;

import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class RetentionServiceTest {

    private static final long T0 = 1_000_000_000L;

    private KvStore kvStore;
    private RetentionProperties properties;
    private MutableClock clock;
    private RetentionService service;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        properties = new RetentionProperties();
        clock = new MutableClock(T0);
        CompactionMetrics metrics = new CompactionMetrics(
                new SimpleMeterRegistry(), kvStore);
        service = new RetentionService(
                kvStore, properties, metrics, clock);
    }

    @Test
    void evictsRecordsPastDefaultTtl() {
        seed("k1", T0 - Duration.ofHours(2).toMillis());
        seed("k2", T0 - Duration.ofMinutes(5).toMillis());
        properties.setDefaultTtl(Duration.ofHours(1));

        int evicted = service.sweep();

        assertThat(evicted).isEqualTo(1);
        assertThat(kvStore.get("k1")).isEmpty();
        assertThat(kvStore.get("k2")).isPresent();
    }

    @Test
    void prefixRuleOverridesDefault() {
        seed("orders/A", T0 - Duration.ofHours(8).toMillis());
        seed("ephemeral/X", T0 - Duration.ofMinutes(2).toMillis());

        properties.setDefaultTtl(Duration.ofDays(7));
        addRule("orders/", Duration.ofHours(1));
        addRule("ephemeral/", Duration.ofMinutes(1));

        int evicted = service.sweep();

        assertThat(evicted).isEqualTo(2);
        assertThat(kvStore.get("orders/A")).isEmpty();
        assertThat(kvStore.get("ephemeral/X")).isEmpty();
    }

    @Test
    void longestPrefixWins() {
        seed("a/b/c/key", T0 - Duration.ofMinutes(30).toMillis());
        properties.setDefaultTtl(Duration.ofDays(1));
        addRule("a/", Duration.ofHours(1));
        addRule("a/b/", Duration.ofMinutes(10));
        // Most specific (a/b/) wins -> ttl 10min, age 30min -> evict
        addRule("a/b/c/", Duration.ofMinutes(60));
        // Even longer (a/b/c/) -> 60min, age 30min -> KEEP

        int evicted = service.sweep();

        assertThat(evicted).isZero();
        assertThat(kvStore.get("a/b/c/key")).isPresent();
    }

    @Test
    void nullTtlMeansKeepForever() {
        seed("kept", T0 - Duration.ofDays(365).toMillis());
        properties.setDefaultTtl(null);

        int evicted = service.sweep();

        assertThat(evicted).isZero();
        assertThat(kvStore.get("kept")).isPresent();
    }

    @Test
    void nullDefaultPlusUnmatchedKeyKeepsRecord() {
        seed("orders/A", T0 - Duration.ofDays(7).toMillis());
        properties.setDefaultTtl(null);
        addRule("invoices/", Duration.ofHours(1));

        int evicted = service.sweep();

        assertThat(evicted).isZero();
        assertThat(kvStore.get("orders/A")).isPresent();
    }

    @Test
    void emptyStoreSweepIsNoOp() {
        properties.setDefaultTtl(Duration.ofHours(1));

        int evicted = service.sweep();

        assertThat(evicted).isZero();
    }

    private void seed(String key, long ingestTs) {
        kvStore.put(key, new CompactedRecord(
                "x".getBytes(StandardCharsets.UTF_8),
                Map.of(),
                key, ingestTs, null));
    }

    private void addRule(String prefix, Duration ttl) {
        RetentionProperties.Rule rule = new RetentionProperties.Rule();
        rule.setPrefix(prefix);
        rule.setTtl(ttl);
        properties.getRules().add(rule);
    }

    private static final class MutableClock extends Clock {
        private long nowMillis;

        MutableClock(long nowMillis) {
            this.nowMillis = nowMillis;
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return Instant.ofEpochMilli(nowMillis);
        }
    }
}
