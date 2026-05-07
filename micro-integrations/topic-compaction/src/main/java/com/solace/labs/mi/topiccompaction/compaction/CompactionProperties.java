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
 *   audit:
 *     enabled: true             # emit audit events on the audit-suffix topic
 *     client-name-suffix: -audit
 * </pre>
 *
 * <p>V1.1.0 changes audit emission semantics: audits are now fired
 * via {@code DirectAuditPublisher} on a separate JCSMP session with
 * {@code DeliveryMode.DIRECT}. The legacy output-0 PERSISTENT path
 * via the binder is suppressed because (a) the binder hardcodes
 * PERSISTENT in {@code XMLMessageMapper.mapToSmf}, (b) the broker
 * silently discards JCSMP-from-MI-client publishes that route back
 * to the same queue, and (c) audit is fire-and-forget observability
 * - it must not gate the consumer-ack on the inbound message.
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

    private final Audit audit = new Audit();

    public Set<String> getBindingNames() { return bindingNames; }
    public void setBindingNames(Set<String> bindingNames) { this.bindingNames = bindingNames; }
    public String getAuditSuffix() { return auditSuffix; }
    public void setAuditSuffix(String auditSuffix) { this.auditSuffix = auditSuffix; }
    public String getLoopProtectionHeader() { return loopProtectionHeader; }
    public void setLoopProtectionHeader(String h) { this.loopProtectionHeader = h; }
    public Ordering getOrdering() { return ordering; }
    public Audit getAudit() { return audit; }

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

    /**
     * Audit emission configuration (V1.1.0+).
     *
     * <p>When {@link #enabled} is true the {@code DirectAuditPublisher}
     * fires a fire-and-forget audit event on
     * {@code <topic><audit-suffix>} via a SEPARATE JCSMP session with
     * {@code DeliveryMode.DIRECT}. The session is opened once at
     * startup and reused for the lifetime of the application;
     * failures are logged but never fail the consumer-ack on the
     * inbound message.
     *
     * <p>When false: no audit emission, no separate session, no
     * publisher attached. The compaction workflow becomes pure
     * input-0 -> KV (no observable side effect on the broker
     * besides the inbound consumer-ack itself).
     */
    public static class Audit {
        /**
         * Master switch. Default {@code true} for backward-compat.
         * Operators who don't consume the audit topic should flip
         * this to {@code false} to remove the publish overhead and
         * the entire publish-failure-discovery surface.
         */
        private boolean enabled = true;

        /**
         * Suffix appended to the binder-managed JCSMP client name
         * for the audit publisher's separate session. Decoupling
         * the client name is required so that the broker treats
         * the audit publish as coming from a DIFFERENT client than
         * the one consuming {@code compaction.data} - this avoids
         * the same-session publish-discard observed in V1.0.x with
         * Solace Cloud 10.x brokers.
         */
        private String clientNameSuffix = "-audit";

        /**
         * Connect timeout for the audit session, in milliseconds.
         * Conservative default; failures here are logged at WARN
         * during startup but do not block the application.
         */
        private long connectTimeoutMillis = 10_000L;

        public boolean isEnabled() { return enabled; }
        public void setEnabled(boolean v) { this.enabled = v; }

        public String getClientNameSuffix() { return clientNameSuffix; }
        public void setClientNameSuffix(String v) { this.clientNameSuffix = v; }

        public long getConnectTimeoutMillis() { return connectTimeoutMillis; }
        public void setConnectTimeoutMillis(long v) { this.connectTimeoutMillis = v; }
    }
}
