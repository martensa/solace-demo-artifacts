package com.solace.labs.mi.topiccompaction.observability;

import io.micrometer.core.aop.CountedAspect;
import io.micrometer.core.aop.TimedAspect;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.observation.ObservationRegistry;
import io.micrometer.observation.aop.ObservedAspect;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires the AOP plumbing that turns
 * {@link io.micrometer.observation.annotation.Observed @Observed},
 * {@link io.micrometer.core.annotation.Timed @Timed}, and
 * {@link io.micrometer.core.annotation.Counted @Counted} method
 * annotations into actual spans, timers, and counters.
 *
 * <p>The Spring Boot starter brings in Micrometer Observation but
 * does not register the aspect beans automatically. Without these
 * beans the annotations are silently ignored.
 *
 * <p>Trace propagation into the SLF4J MDC is handled by the OTel
 * tracing bridge auto-configuration; no extra wiring needed here.
 */
@Configuration
public class TracingConfig {

    @Bean
    public ObservedAspect observedAspect(
            ObservationRegistry observationRegistry) {
        return new ObservedAspect(observationRegistry);
    }

    @Bean
    public TimedAspect timedAspect(MeterRegistry registry) {
        return new TimedAspect(registry);
    }

    @Bean
    public CountedAspect countedAspect(MeterRegistry registry) {
        return new CountedAspect(registry);
    }
}
