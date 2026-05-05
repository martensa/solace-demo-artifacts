package com.solace.labs.mi.topiccompaction.retention;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * Operator-tunable retention/TTL settings for the KV store.
 *
 * <p>Disabled by default. When enabled, a scheduler scans the KV
 * store on a configurable interval and evicts records whose
 * {@code ingestTimestamp} plus the matching TTL is in the past.
 *
 * <pre>
 * topic-compaction:
 *   retention:
 *     enabled: true
 *     check-interval: PT5M
 *     default-ttl: PT24H
 *     rules:
 *       - prefix: "orders/"
 *         ttl: PT7D
 *       - prefix: "ephemeral/"
 *         ttl: PT1H
 * </pre>
 *
 * <p>Rule matching uses longest-prefix-first; falls back to the
 * default TTL when no rule matches. A {@code null} TTL means "never
 * evict for this prefix".
 */
@ConfigurationProperties(prefix = "topic-compaction.retention")
public class RetentionProperties {

    /** Master switch. */
    private boolean enabled = false;

    /** Scan interval. Defaults to 5 minutes. */
    private Duration checkInterval = Duration.ofMinutes(5);

    /**
     * Default TTL applied when no per-prefix rule matches. Null
     * means records without a matching rule are kept forever.
     */
    private Duration defaultTtl;

    /** Per-prefix TTL overrides. */
    private List<Rule> rules = new ArrayList<>();

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean v) { this.enabled = v; }

    public Duration getCheckInterval() { return checkInterval; }
    public void setCheckInterval(Duration v) { this.checkInterval = v; }

    public Duration getDefaultTtl() { return defaultTtl; }
    public void setDefaultTtl(Duration v) { this.defaultTtl = v; }

    public List<Rule> getRules() { return rules; }
    public void setRules(List<Rule> v) { this.rules = v; }

    /**
     * Resolve the TTL that applies to {@code key}. Picks the
     * longest-matching prefix, falls back to the default. A null
     * return means "do not evict".
     */
    public Duration resolveTtl(String key) {
        return rules.stream()
                .filter(r -> key.startsWith(r.getPrefix()))
                .max(Comparator.comparingInt(
                        r -> r.getPrefix().length()))
                .map(Rule::getTtl)
                .orElse(defaultTtl);
    }

    /** Single per-prefix retention rule. */
    public static class Rule {
        private String prefix = "";
        private Duration ttl;

        public String getPrefix() { return prefix; }
        public void setPrefix(String v) { this.prefix = v; }

        public Duration getTtl() { return ttl; }
        public void setTtl(Duration v) { this.ttl = v; }
    }
}
