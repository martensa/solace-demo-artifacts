package com.solace.labs.mi.topiccompaction.replay;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.labs.mi.topiccompaction.command.CommandEventParser;
import com.solace.labs.mi.topiccompaction.delete.DeleteCommandService;
import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.core.io.ClassPathResource;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.GenericMessage;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ReplayProducerInterceptorTest {

    private ReplayProducerInterceptorFactory factory;
    private KvStore kvStore;
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() throws IOException {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        objectMapper = new ObjectMapper();
        ReplayProperties props = new ReplayProperties();
        CommandEventParser parser = new CommandEventParser(
                objectMapper,
                new ClassPathResource("schemas/command-event-v1.json"));
        parser.init();
        CompactionMetrics metrics = new CompactionMetrics(
                new SimpleMeterRegistry(), kvStore);
        ReplayService replayService = new ReplayService(
                kvStore, props, objectMapper, parser, metrics);
        BulkReplayService bulkReplayService = new BulkReplayService(
                kvStore, props,
                org.mockito.Mockito.mock(
                        org.springframework.cloud.stream.function
                                .StreamBridge.class),
                metrics);
        DeleteCommandService deleteService =
                new DeleteCommandService(kvStore, metrics);
        factory = new ReplayProducerInterceptorFactory(
                replayService, bulkReplayService, deleteService,
                parser, objectMapper, props);
    }

    @Test
    void onlyAttachesToConfiguredOutputBinding() {
        ProducerProperties out1 = props("output-1");
        ProducerProperties out2 = props("output-2");
        assertThat(factory.createIfNecessary("solace", out1)).isNotNull();
        assertThat(factory.createIfNecessary("solace", out2)).isNull();
    }

    @Test
    void rewritesPayloadAndDestinationOnSuccessfulReplay() {
        kvStore.put("orders/12345", new CompactedRecord(
                "the-original".getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", "orders/12345", "content-type", "text/plain"),
                "orders/12345", 100L, null));

        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", props("output-1"));

        Message<?> input = new GenericMessage<>(
                "{\"command\":\"REPLAY\",\"key\":\"orders/12345\"}".getBytes(StandardCharsets.UTF_8));
        Message<?> rewritten = interceptor.before(input);

        assertThat(new String((byte[]) rewritten.getPayload(), StandardCharsets.UTF_8))
                .isEqualTo("the-original");
        assertThat(rewritten.getHeaders().get("solace_destination"))
                .isEqualTo("orders/12345/compacted");
        assertThat(rewritten.getHeaders().get("x-compacted-replay")).isEqualTo(true);
    }

    @Test
    void publishesFailureDocumentToFailureTopicOnUnknownKey() throws Exception {
        ProducerBindingMessageInterceptor interceptor =
                factory.createIfNecessary("solace", props("output-1"));

        Message<?> input = new GenericMessage<>(
                "{\"command\":\"REPLAY\",\"key\":\"nope\"}".getBytes(StandardCharsets.UTF_8));
        Message<?> rewritten = interceptor.before(input);

        assertThat(rewritten.getHeaders().get("solace_destination"))
                .isEqualTo("topic-compaction/replay/failed");
        @SuppressWarnings("unchecked")
        Map<String, Object> doc = objectMapper.readValue((byte[]) rewritten.getPayload(), Map.class);
        assertThat(doc).containsEntry("status", "failed");
    }

    private static ProducerProperties props(String bindingName) {
        ProducerProperties p = new ProducerProperties();
        p.populateBindingName(bindingName);
        return p;
    }
}
