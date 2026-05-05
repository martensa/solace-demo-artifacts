package com.solace.labs.mi.topiccompaction.observability;

import io.micrometer.core.instrument.Clock;
import io.micrometer.core.instrument.Tags;
import io.micrometer.core.instrument.config.MeterFilter;
import io.micrometer.prometheusmetrics.PrometheusConfig;
import io.micrometer.prometheusmetrics.PrometheusMeterRegistry;
import io.prometheus.metrics.model.registry.PrometheusRegistry;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

/**
 * Wires Micrometer's Prometheus registry as the {@code @Primary}
 * {@link io.micrometer.core.instrument.MeterRegistry}, overriding the
 * MI Framework's NoOp meter registry that would otherwise swallow all
 * metrics. Without this configuration the
 * {@code /actuator/prometheus} endpoint returns an empty payload.
 *
 * <p>Common tags are attached to every metric via a
 * {@link MeterFilter} so dashboards can slice by application,
 * version, and Kubernetes namespace without per-metric tagging.
 */
@Configuration
public class MetricsConfig {

    @Value("${spring.application.name:topic-compaction-mi}")
    private String applicationName;

    @Value("${topic-compaction.version:dev}")
    private String version;

    @Value("${KUBERNETES_NAMESPACE:local}")
    private String namespace;

    /**
     * Primary {@link PrometheusMeterRegistry} bean. Marked
     * {@code @Primary} so all autowired {@code MeterRegistry}
     * injections (including {@code CompactionMetrics}) bind to this
     * registry instead of the framework's NoOp default.
     *
     * <p>The shared {@link PrometheusRegistry} is injected from
     * Spring Boot's
     * {@code PrometheusMetricsExportAutoConfiguration} so that this
     * meter registry writes to the same collector that the
     * {@code /actuator/prometheus} scrape endpoint reads from. Without
     * the injection the endpoint would scrape an unrelated empty
     * collector.
     */
    @Bean
    @Primary
    @ConditionalOnBean(PrometheusRegistry.class)
    public PrometheusMeterRegistry prometheusMeterRegistry(
            PrometheusRegistry prometheusRegistry) {
        return new PrometheusMeterRegistry(
                PrometheusConfig.DEFAULT,
                prometheusRegistry,
                Clock.SYSTEM);
    }

    /**
     * Attach common tags to every meter so Prometheus queries can
     * filter consistently. Service identity tags first, then the
     * deployment-environment tag.
     */
    @Bean
    public MeterFilter commonTagsFilter() {
        return MeterFilter.commonTags(Tags.of(
                "application", applicationName,
                "version", version,
                "namespace", namespace));
    }
}
