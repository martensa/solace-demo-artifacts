package com.solace.labs.mi.topiccompaction.lookup;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.HashSet;
import java.util.Set;

/**
 * Configuration properties for the Solace Request/Reply lookup (Workflow 2)
 * flow.
 *
 * <pre>
 * topic-compaction.lookup:
 *   binding-names: [input-2]      # Solace consumer binding for lookup requests
 *   key-header: x-compaction-key  # header carrying the requested key
 * </pre>
 *
 * <p>Operators configure the lookup queue with a subscription pattern, e.g.
 * {@code compacted/lookup/>}. Clients publish a request message with a Solace
 * reply-to header (standard Solace Request/Reply pattern). The MI extracts the
 * key either from the {@link #keyHeader} user property or, if absent, from the
 * request topic's tail segments.
 */
@ConfigurationProperties(prefix = "topic-compaction.lookup")
public class LookupProperties {

    private Set<String> bindingNames = new HashSet<>(Set.of("input-2"));
    private String keyHeader = "x-compaction-key";

    /**
     * If set, the key is extracted from the request topic by stripping this
     * prefix. Example: {@code compacted/lookup/} with request
     * {@code compacted/lookup/orders/12345} yields key {@code orders/12345}.
     * Empty/null means use only the {@link #keyHeader} header.
     */
    private String topicKeyPrefix = "compacted/lookup/";

    public Set<String> getBindingNames() { return bindingNames; }
    public void setBindingNames(Set<String> bindingNames) { this.bindingNames = bindingNames; }
    public String getKeyHeader() { return keyHeader; }
    public void setKeyHeader(String keyHeader) { this.keyHeader = keyHeader; }
    public String getTopicKeyPrefix() { return topicKeyPrefix; }
    public void setTopicKeyPrefix(String topicKeyPrefix) { this.topicKeyPrefix = topicKeyPrefix; }
}
