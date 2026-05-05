package com.solace.labs.mi.topiccompaction.observability;

import com.solace.labs.mi.topiccompaction.compaction.CompactionProperties;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.lookup.LookupProperties;
import com.solace.labs.mi.topiccompaction.provisioning
        .ProvisioningProperties;
import com.solace.labs.mi.topiccompaction.replay.ReplayProperties;
import com.solace.labs.mi.topiccompaction.retention.RetentionProperties;
import com.solace.labs.mi.topiccompaction.security.SecurityProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * Logs a one-shot summary of resolved configuration on
 * {@link ApplicationReadyEvent}. Sensitive values are masked.
 *
 * <p>Helps operators sanity-check what the running container
 * actually loaded - missing env-var substitutions show up as
 * literal {@code ${...}} placeholders, wrong defaults show their
 * default value, and the set of enabled features is clear.
 */
@Component
public class StartupBanner {

    private static final Logger log =
            LoggerFactory.getLogger(StartupBanner.class);

    private final KvStoreProperties kvStoreProperties;
    private final CompactionProperties compactionProperties;
    private final ReplayProperties replayProperties;
    private final LookupProperties lookupProperties;
    private final SecurityProperties securityProperties;
    private final ObjectProvider<RetentionProperties>
            retentionProperties;
    private final ObjectProvider<ProvisioningProperties>
            provisioningProperties;

    @Value("${spring.application.name:topic-compaction-mi}")
    private String applicationName;

    @Value("${topic-compaction.version:dev}")
    private String version;

    @Value("${OTEL_EXPORTER_OTLP_ENDPOINT:not-set}")
    private String otelEndpoint;

    public StartupBanner(
            KvStoreProperties kvStoreProperties,
            CompactionProperties compactionProperties,
            ReplayProperties replayProperties,
            LookupProperties lookupProperties,
            SecurityProperties securityProperties,
            ObjectProvider<RetentionProperties> retentionProperties,
            ObjectProvider<ProvisioningProperties>
                    provisioningProperties) {
        this.kvStoreProperties = kvStoreProperties;
        this.compactionProperties = compactionProperties;
        this.replayProperties = replayProperties;
        this.lookupProperties = lookupProperties;
        this.securityProperties = securityProperties;
        this.retentionProperties = retentionProperties;
        this.provisioningProperties = provisioningProperties;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void onReady() {
        StringBuilder b = new StringBuilder();
        b.append("\n");
        b.append(line("="));
        b.append(String.format("  %s v%s%n",
                applicationName, version));
        b.append(line("-"));
        b.append(String.format("  KV store backend     : %s%n",
                kvStoreProperties.getBackend()));
        b.append(String.format("  KV store path        : %s%n",
                kvStoreProperties.getRocksdb().getPath()));
        b.append(String.format("  Compaction audit     : <topic>%s%n",
                compactionProperties.getAuditSuffix()));
        b.append(String.format("  Replay target        : <key>%s%n",
                replayProperties.getTargetSuffix()));
        b.append(String.format("  Lookup key header    : %s%n",
                lookupProperties.getKeyHeader()));
        b.append(String.format(
                "  Lookup topic prefix  : %s%n",
                lookupProperties.getTopicKeyPrefix()));
        b.append(String.format(
                "  REST security        : %s%n",
                securityProperties.isEnabled()
                        ? "ENABLED user=" + maskName(
                                securityProperties.getUser().getName())
                                + " admin=" + maskName(
                                securityProperties.getAdmin().getName())
                        : "disabled"));
        b.append(String.format(
                "  Retention sweeper    : %s%n",
                retentionStatus()));
        b.append(String.format(
                "  Broker provisioning  : %s%n",
                provisioningStatus()));
        b.append(String.format(
                "  OTLP tracing endpoint: %s%n",
                otelEndpoint));
        b.append(line("="));
        log.info(b.toString());
    }

    private String retentionStatus() {
        RetentionProperties p = retentionProperties.getIfAvailable();
        if (p == null || !p.isEnabled()) {
            return "disabled";
        }
        return String.format(
                "ENABLED interval=%s default-ttl=%s rules=%d",
                p.getCheckInterval(), p.getDefaultTtl(),
                p.getRules().size());
    }

    private String provisioningStatus() {
        ProvisioningProperties p =
                provisioningProperties.getIfAvailable();
        if (p == null || !p.isEnabled()) {
            return "disabled";
        }
        return String.format(
                "ENABLED semp=%s vpn=%s queues=%d "
                        + "fail-on-error=%s",
                p.getSemp().getUrl(),
                p.getSemp().getMsgVpn(),
                p.getQueues().size(),
                p.isFailOnError());
    }

    private static String maskName(String name) {
        if (name == null || name.isEmpty()) {
            return "<unset>";
        }
        // Show the first character + asterisks; usernames are not
        // strictly secret but we avoid logging them in full anyway.
        return name.charAt(0) + "***";
    }

    private static String line(String chr) {
        return "  " + chr.repeat(70) + "\n";
    }
}
