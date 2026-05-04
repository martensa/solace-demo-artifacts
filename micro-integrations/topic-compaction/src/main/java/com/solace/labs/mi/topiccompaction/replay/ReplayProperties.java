package com.solace.labs.mi.topiccompaction.replay;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.HashSet;
import java.util.Set;

/**
 * Configuration properties for the replay (Workflow 1) flow.
 *
 * <pre>
 * topic-compaction.replay:
 *   binding-names: [input-1]    # Solace consumer binding(s) for the command queue
 *   target-suffix: /compacted   # appended to the original topic for replay output
 *   loop-protection-header: x-compacted-replay
 * </pre>
 */
@ConfigurationProperties(prefix = "topic-compaction.replay")
public class ReplayProperties {

    /**
     * The binding names of Solace consumer bindings that carry replay command
     * events. Defaults to {@code input-1}.
     */
    private Set<String> bindingNames = new HashSet<>(Set.of("input-1"));

    /**
     * Suffix appended to the original topic when republishing during replay.
     * Per requirements: defaults to {@code /compacted}.
     */
    private String targetSuffix = "/compacted";

    /**
     * Solace user-property header set on replay messages so the compaction flow
     * can short-circuit and avoid loops.
     */
    private String loopProtectionHeader = "x-compacted-replay";

    public Set<String> getBindingNames() { return bindingNames; }
    public void setBindingNames(Set<String> bindingNames) { this.bindingNames = bindingNames; }
    public String getTargetSuffix() { return targetSuffix; }
    public void setTargetSuffix(String targetSuffix) { this.targetSuffix = targetSuffix; }
    public String getLoopProtectionHeader() { return loopProtectionHeader; }
    public void setLoopProtectionHeader(String h) { this.loopProtectionHeader = h; }
}
