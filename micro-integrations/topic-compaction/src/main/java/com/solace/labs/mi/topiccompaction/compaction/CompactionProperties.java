package com.solace.labs.mi.topiccompaction.compaction;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.HashSet;
import java.util.Set;

/**
 * Configuration properties for the compaction (Workflow 0) flow.
 *
 * <pre>
 * topic-compaction.compaction:
 *   binding-names: [input-0]    # Solace consumer binding(s) that feed into compaction
 *   audit-suffix: /compacted-ack
 *   loop-protection-header: x-compacted-replay
 *   ordering:
 *     header: ""                # empty = always-last-wins; e.g. "senderTimestamp"
 * </pre>
 */
@ConfigurationProperties(prefix = "topic-compaction.compaction")
public class CompactionProperties {

    /**
     * The binding names of Solace consumer bindings that feed into the compaction
     * KV store. Defaults to {@code input-0}; operators with multiple compaction
     * sources can list more.
     */
    private Set<String> bindingNames = new HashSet<>(Set.of("input-0"));

    /**
     * Suffix appended to the original topic when emitting the audit event.
     */
    private String auditSuffix = "/compacted-ack";

    /**
     * Solace user-property header set on replay messages so the compaction flow
     * can short-circuit and avoid loops. Set to empty string to disable.
     */
    private String loopProtectionHeader = "x-compacted-replay";

    private final Ordering ordering = new Ordering();

    public Set<String> getBindingNames() { return bindingNames; }
    public void setBindingNames(Set<String> bindingNames) { this.bindingNames = bindingNames; }
    public String getAuditSuffix() { return auditSuffix; }
    public void setAuditSuffix(String auditSuffix) { this.auditSuffix = auditSuffix; }
    public String getLoopProtectionHeader() { return loopProtectionHeader; }
    public void setLoopProtectionHeader(String h) { this.loopProtectionHeader = h; }
    public Ordering getOrdering() { return ordering; }

    /**
     * Optional sender-supplied ordering. When {@link #header} names a Solace user
     * property containing a parseable {@code long} timestamp, the compaction
     * interceptor compares it against any existing record and refuses to write
     * if the incoming message is older.
     */
    public static class Ordering {
        private String header = "";

        public String getHeader() { return header; }
        public void setHeader(String header) { this.header = header; }

        public boolean enabled() {
            return header != null && !header.isBlank();
        }
    }
}
