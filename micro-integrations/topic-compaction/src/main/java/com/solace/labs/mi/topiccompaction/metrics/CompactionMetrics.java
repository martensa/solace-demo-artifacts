package com.solace.labs.mi.topiccompaction.metrics;

import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Tags;
import org.springframework.stereotype.Component;

/**
 * Micrometer counters and gauges for the topic-compaction MI.
 *
 * <p>All metric names are prefixed {@code topic_compaction_} for easy Prometheus
 * scraping and Grafana dashboards.
 */
@Component
public class CompactionMetrics {

    private final Counter upserts;
    private final Counter loopSkips;
    private final Counter outOfOrderSkips;
    private final Counter replays;
    private final Counter lookups;
    private final Counter lookupMisses;

    public CompactionMetrics(MeterRegistry registry, KvStore kvStore) {
        this.upserts = Counter.builder("topic_compaction_upserts_total")
                .description("Number of compaction upserts written to the KV store")
                .register(registry);
        this.loopSkips = Counter.builder("topic_compaction_skipped_total")
                .description("Number of messages skipped by compaction")
                .tags(Tags.of("reason", "loop"))
                .register(registry);
        this.outOfOrderSkips = Counter.builder("topic_compaction_skipped_total")
                .description("Number of messages skipped by compaction")
                .tags(Tags.of("reason", "out_of_order"))
                .register(registry);
        this.replays = Counter.builder("topic_compaction_replays_total")
                .description("Number of replay events successfully published")
                .register(registry);
        this.lookups = Counter.builder("topic_compaction_lookups_total")
                .description("Number of KV lookup requests")
                .register(registry);
        this.lookupMisses = Counter.builder("topic_compaction_lookup_misses_total")
                .description("Number of KV lookup requests that returned no record")
                .register(registry);

        registry.gauge("topic_compaction_kvstore_size", kvStore, KvStore::size);
    }

    public void recordUpsert() { upserts.increment(); }
    public void recordLoopSkip() { loopSkips.increment(); }
    public void recordOutOfOrderSkip() { outOfOrderSkips.increment(); }
    public void recordReplay() { replays.increment(); }
    public void recordLookup() { lookups.increment(); }
    public void recordLookupMiss() { lookupMisses.increment(); }
}
