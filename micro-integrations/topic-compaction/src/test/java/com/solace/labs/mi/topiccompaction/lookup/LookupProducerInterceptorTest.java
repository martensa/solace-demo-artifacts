package com.solace.labs.mi.topiccompaction.lookup;

import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * V1.1.4 contract: the lookup workflow's producer interceptor is
 * now a pure SUPPRESSOR. The actual lookup work (KV resolve +
 * reply publish) moved to {@link LookupConsumerInterceptorFactory}
 * on the consumer side; the reply is fired DIRECT via
 * {@code DirectAuditPublisher.publishDirectBytes} so the binder
 * publish path is no longer involved. This interceptor returns
 * {@code null} for every message to ensure the binder skips its
 * publish (which would otherwise PERSIST to a DIRECT-only
 * temp reply queue and hang).
 */
class LookupProducerInterceptorTest {

    private LookupProducerInterceptorFactory factory;

    @BeforeEach
    void setUp() {
        LookupProperties props = new LookupProperties();
        factory = new LookupProducerInterceptorFactory(props);
    }

    @Test
    void onlyAttachesToConfiguredOutputBinding() {
        ProducerProperties out2 = props("output-2");
        ProducerProperties out0 = props("output-0");
        assertThat(factory.createIfNecessary("solace", out2)).isNotNull();
        assertThat(factory.createIfNecessary("solace", out0)).isNull();
    }

    @Test
    void doesNotAttachToNonSolaceBinder() {
        assertThat(factory.createIfNecessary("kafka", props("output-2"))).isNull();
    }

    @Test
    void suppressesAnyPublishOnTheLookupOutputBinding() {
        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", props("output-2"));
        Message<?> any = MessageBuilder.withPayload(new byte[0])
                .setHeader("x-compaction-key", "orders/12345")
                .setHeader("solace_replyTo", "client/reply/abc-123")
                .build();
        assertThat(interceptor.before(any)).isNull();
    }

    private static ProducerProperties props(String bindingName) {
        ProducerProperties p = new ProducerProperties();
        p.populateBindingName(bindingName);
        return p;
    }
}
