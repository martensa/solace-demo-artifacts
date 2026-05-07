package com.solace.labs.mi.topiccompaction.observability;

import com.solacesystems.jcsmp.SDTException;
import com.solacesystems.jcsmp.SDTMap;
import io.micrometer.tracing.Span;
import io.micrometer.tracing.TraceContext;
import io.micrometer.tracing.Tracer;
import io.micrometer.tracing.propagation.Propagator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/**
 * V1.2.0: end-to-end W3C trace context propagation across Solace
 * messages via Micrometer Tracing's {@link Propagator} +
 * {@link Tracer}.
 *
 * <p>Two carrier shapes are involved:
 * <ul>
 *   <li><b>Inbound</b> messages arrive at consumer interceptors as
 *       {@link Message Spring Messages}. The Solace binder
 *       converts inbound Solace user properties into Spring message
 *       headers with the same key, so {@code traceparent} /
 *       {@code tracestate} land directly in the message headers.</li>
 *   <li><b>Outbound</b> messages emitted via
 *       {@code DirectAuditPublisher} are raw JCSMP {@code BytesMessage}
 *       instances; their user properties live in an
 *       {@link SDTMap}. Outbound messages emitted via
 *       {@link org.springframework.cloud.stream.function.StreamBridge}
 *       are Spring Messages whose headers the Solace binder copies
 *       into the SDT map on send.</li>
 * </ul>
 *
 * <p>Why Micrometer's API rather than raw OpenTelemetry: the
 * {@code @Observed} annotations are created via Micrometer
 * Observation, which keeps its own thread-local state. The OTel
 * bridge keeps Micrometer's {@link Tracer#currentSpan()} in sync
 * with OTel's {@code Span.current()} only when spans are entered
 * via Micrometer's {@link Tracer#withSpan(Span)}; entering an OTel
 * span via raw {@code Scope.makeCurrent()} would leave Micrometer's
 * thread-local unchanged and {@code @Observed}-created spans would
 * become trace roots. Routing through Micrometer guarantees
 * {@code @Observed} sees the upstream context as parent.
 *
 * <p>Per-message structure:
 *
 * <pre>
 *   upstream publisher span (extracted from traceparent)
 *     └─ inbound-receive span (this helper, named by workflow)
 *        └─ compact-message / lookup-request / replay-command (@Observed)
 *           └─ ... nested work spans
 * </pre>
 */
@Component
public class SolaceContextPropagation {

    private static final Logger log = LoggerFactory.getLogger(
            SolaceContextPropagation.class);

    private final Tracer tracer;
    private final Propagator propagator;

    private final Propagator.Getter<Message<?>> springGetter =
            new SpringMessageGetter();
    private final Propagator.Setter<SDTMap> sdtMapSetter =
            new SdtMapSetter();
    private final Propagator.Setter<Map<String, String>> mapSetter =
            (carrier, key, value) -> {
                if (carrier != null && key != null && value != null) {
                    carrier.put(key, value);
                }
            };

    public SolaceContextPropagation(Tracer tracer, Propagator propagator) {
        this.tracer = tracer;
        this.propagator = propagator;
    }

    /**
     * Extract the upstream context from an inbound Spring Message,
     * start a child {@code inbound-receive} span named by workflow,
     * and make it current on the calling thread. The returned
     * {@link InboundScope} ends the span and releases the scope on
     * {@link InboundScope#close()}.
     *
     * <p>If the inbound has no {@code traceparent} header (e.g. an
     * uninstrumented publisher), the extracted builder returns a
     * trace-root span. Either way, subsequent
     * {@code @Observed}-created spans become children of the
     * receive span - and through it, of the upstream trace if
     * present.
     */
    public InboundScope extractAndStart(Message<?> message,
                                          String workflowName) {
        try {
            Span.Builder builder = propagator.extract(message, springGetter);
            Span span = builder.name(workflowName).kind(Span.Kind.CONSUMER).start();
            Tracer.SpanInScope inScope = tracer.withSpan(span);
            return new InboundScope(span, inScope);
        } catch (RuntimeException e) {
            log.warn("SolaceContextPropagation: extract failed for workflow={}: {}",
                    workflowName, e.getMessage());
            return InboundScope.noop();
        }
    }

    /**
     * Inject the currently-active span context into a JCSMP SDT
     * user-property map. Call this before
     * {@code XMLMessageProducer.send()} so the downstream consumer
     * can extract and link.
     *
     * <p>If no span is active, the propagator is a no-op (no
     * headers added).
     */
    public void injectInto(@Nullable SDTMap userProperties) {
        if (userProperties == null) return;
        TraceContext ctx = currentContext();
        if (ctx == null) return;
        try {
            propagator.inject(ctx, userProperties, sdtMapSetter);
        } catch (RuntimeException e) {
            log.debug("SolaceContextPropagation: SDTMap inject failed: {}",
                    e.getMessage());
        }
    }

    /**
     * Snapshot the currently-active span context as a plain
     * {@code Map<String,String>} suitable for forwarding into
     * Spring {@link org.springframework.messaging.support.MessageBuilder}
     * via {@code .setHeader(k, v)}. Used by StreamBridge call sites
     * (single REPLAY, BULK_REPLAY fan-out) where the Solace binder
     * copies Spring headers into Solace user properties on send.
     */
    public Map<String, String> currentContextAsHeaders() {
        TraceContext ctx = currentContext();
        if (ctx == null) {
            return Collections.emptyMap();
        }
        Map<String, String> carrier = new HashMap<>();
        propagator.inject(ctx, carrier, mapSetter);
        return carrier;
    }

    @Nullable
    private TraceContext currentContext() {
        Span current = tracer.currentSpan();
        return current == null ? null : current.context();
    }

    /**
     * Try-with-resources scope returned by
     * {@link #extractAndStart(Message, String)}. Closing it ends
     * the receive span and releases the {@link Tracer.SpanInScope}.
     */
    public static final class InboundScope implements AutoCloseable {
        @Nullable private final Span span;
        @Nullable private final Tracer.SpanInScope inScope;

        private InboundScope(@Nullable Span span,
                              @Nullable Tracer.SpanInScope inScope) {
            this.span = span;
            this.inScope = inScope;
        }

        static InboundScope noop() {
            return new InboundScope(null, null);
        }

        @Override
        public void close() {
            if (inScope != null) {
                try {
                    inScope.close();
                } catch (RuntimeException e) {
                    /* swallow */
                }
            }
            if (span != null) {
                try {
                    span.end();
                } catch (RuntimeException e) {
                    /* swallow */
                }
            }
        }
    }

    private static final class SpringMessageGetter
            implements Propagator.Getter<Message<?>> {
        @Override
        @Nullable
        public String get(@Nullable Message<?> message, String key) {
            if (message == null || key == null) return null;
            Object value = message.getHeaders().get(key);
            if (value == null) return null;
            if (value instanceof String s) return s;
            if (value instanceof byte[] b) return new String(b);
            return value.toString();
        }
    }

    private static final class SdtMapSetter implements Propagator.Setter<SDTMap> {
        @Override
        public void set(@Nullable SDTMap carrier, String key, String value) {
            if (carrier == null || key == null || value == null) return;
            try {
                carrier.putString(key, value);
            } catch (SDTException e) {
                log.debug("SolaceContextPropagation: SDTMap.putString({}, ...) failed: {}",
                        key, e.getMessage());
            }
        }
    }
}
