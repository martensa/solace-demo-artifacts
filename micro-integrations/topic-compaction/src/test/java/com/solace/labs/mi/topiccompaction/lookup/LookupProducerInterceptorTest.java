package com.solace.labs.mi.topiccompaction.lookup;

import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class LookupProducerInterceptorTest {

    private LookupProducerInterceptorFactory factory;
    private KvStore kvStore;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        LookupProperties props = new LookupProperties();
        LookupService service = new LookupService(kvStore, props,
                new CompactionMetrics(new SimpleMeterRegistry(), kvStore));
        factory = new LookupProducerInterceptorFactory(service, props);
    }

    @Test
    void onlyAttachesToConfiguredOutputBinding() {
        ProducerProperties out2 = props("output-2");
        ProducerProperties out0 = props("output-0");
        assertThat(factory.createIfNecessary("solace", out2)).isNotNull();
        assertThat(factory.createIfNecessary("solace", out0)).isNull();
    }

    @Test
    void respondsToReplyToWithStoredPayload() {
        kvStore.put("orders/12345", new CompactedRecord(
                "stored-value".getBytes(StandardCharsets.UTF_8),
                Map.of("content-type", "text/plain"),
                "orders/12345", 100L, null));

        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", props("output-2"));

        Message<?> request = MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "orders/12345")
                .setHeader("solace_replyTo", "client/reply/abc-123")
                .setHeader("solace_correlationId", "corr-1")
                .build();

        Message<?> response = interceptor.before(request);

        assertThat(new String((byte[]) response.getPayload(), StandardCharsets.UTF_8))
                .isEqualTo("stored-value");
        assertThat(response.getHeaders().get("solace_destination"))
                .isEqualTo("client/reply/abc-123");
        assertThat(response.getHeaders().get("solace_correlationId"))
                .isEqualTo("corr-1");
        assertThat(response.getHeaders().get("x-compaction-status")).isEqualTo("found");
    }

    @Test
    void respondsWithNotFoundJsonForUnknownKey() {
        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", props("output-2"));

        Message<?> request = MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "missing")
                .setHeader("solace_replyTo", "client/reply/abc")
                .build();

        Message<?> response = interceptor.before(request);

        assertThat(new String((byte[]) response.getPayload(), StandardCharsets.UTF_8))
                .contains("\"status\":\"not-found\"");
        assertThat(response.getHeaders().get("solace_destination"))
                .isEqualTo("client/reply/abc");
        assertThat(response.getHeaders().get("x-compaction-status")).isEqualTo("not-found");
    }

    private static ProducerProperties props(String bindingName) {
        ProducerProperties p = new ProducerProperties();
        p.populateBindingName(bindingName);
        return p;
    }
}
