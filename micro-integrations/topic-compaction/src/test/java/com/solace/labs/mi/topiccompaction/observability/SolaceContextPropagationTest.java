package com.solace.labs.mi.topiccompaction.observability;

import com.solacesystems.jcsmp.JCSMPFactory;
import com.solacesystems.jcsmp.SDTMap;
import io.micrometer.tracing.Tracer;
import io.micrometer.tracing.propagation.Propagator;
import org.junit.jupiter.api.Test;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * V1.2.0 unit tests for {@link SolaceContextPropagation}.
 *
 * <p>Behavioural verification of the inject/extract paths against
 * a real broker happens in
 * {@code DirectAuditPublisherIT} (Testcontainers). These unit
 * tests focus on the helper's defensive contract: never throw on
 * null carriers, return empty when no span is active, hand back a
 * usable {@link SolaceContextPropagation.InboundScope} for
 * try-with-resources even with the {@link Tracer#NOOP}.
 */
class SolaceContextPropagationTest {

    private final SolaceContextPropagation propagation =
            new SolaceContextPropagation(Tracer.NOOP, Propagator.NOOP);

    @Test
    void extractAndStartReturnsClosableScopeEvenWithNoopTracer() {
        Message<String> message = MessageBuilder.withPayload("payload")
                .setHeader("traceparent",
                        "00-0123456789abcdef0123456789abcdef-fedcba9876543210-01")
                .build();
        try (SolaceContextPropagation.InboundScope scope =
                     propagation.extractAndStart(message, "compaction.inbound")) {
            // Reaching here is the test - no NPE, no throw.
            assertThat(scope).isNotNull();
        }
    }

    @Test
    void extractAndStartHandlesMessageWithoutTraceparent() {
        Message<String> message = MessageBuilder.withPayload("anon").build();
        try (SolaceContextPropagation.InboundScope scope =
                     propagation.extractAndStart(message, "compaction.inbound")) {
            assertThat(scope).isNotNull();
        }
    }

    @Test
    void injectIntoNullSdtMapIsSafe() {
        // Defensive: null carrier should not throw.
        propagation.injectInto(null);
    }

    @Test
    void injectIntoEmptySdtMapDoesNotThrow() throws Exception {
        SDTMap sdt = JCSMPFactory.onlyInstance().createMap();
        propagation.injectInto(sdt);
        // Without an active span the propagator is a no-op; nothing
        // ends up in the map. Verifying the call doesn't throw is
        // the test - real injection is covered by the IT.
        assertThat(sdt.isEmpty()).isTrue();
    }

    @Test
    void currentContextAsHeadersReturnsEmptyMapWhenNoSpan() {
        Map<String, String> headers = propagation.currentContextAsHeaders();
        assertThat(headers).isEmpty();
    }

    @Test
    void closingInboundScopeMultipleTimesIsSafe() {
        Message<String> message = MessageBuilder.withPayload("x").build();
        SolaceContextPropagation.InboundScope scope =
                propagation.extractAndStart(message, "test");
        scope.close();
        // Idempotent close: must not NPE on second call (even if
        // semantically the scope is already done).
        scope.close();
    }
}
