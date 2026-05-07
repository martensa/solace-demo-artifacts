package com.solace.labs.mi.topiccompaction.compaction;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solacesystems.jcsmp.BytesMessage;
import com.solacesystems.jcsmp.DeliveryMode;
import com.solacesystems.jcsmp.JCSMPException;
import com.solacesystems.jcsmp.JCSMPProperties;
import com.solacesystems.jcsmp.JCSMPSession;
import com.solacesystems.jcsmp.SDTMap;
import com.solacesystems.jcsmp.Topic;
import com.solacesystems.jcsmp.XMLMessage;
import com.solacesystems.jcsmp.XMLMessageProducer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.lang.reflect.Field;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;

/**
 * V1.1.0 unit tests for the standalone audit publisher.
 *
 * <p>The full session lifecycle (PostConstruct connect, broker
 * round-trips) is covered by the Testcontainers integration test;
 * here we focus on the publish behaviour by injecting a mocked
 * {@link XMLMessageProducer} via reflection. This keeps the unit
 * tests fast and decoupled from a running broker.
 */
class DirectAuditPublisherTest {

    private ObjectMapper objectMapper;
    private CompactionProperties properties;
    private JCSMPProperties baseProperties;
    private JCSMPSession session;
    private XMLMessageProducer producer;
    private DirectAuditPublisher publisher;

    @BeforeEach
    void setUp() throws Exception {
        objectMapper = new ObjectMapper();
        properties = new CompactionProperties();
        baseProperties = new JCSMPProperties();
        // Setting any non-null host avoids JCSMPProperties.clone()
        // tripping over uninitialised internal state in some versions.
        baseProperties.setProperty(JCSMPProperties.HOST, "tcp://localhost:55555");

        session = mock(JCSMPSession.class);
        producer = mock(XMLMessageProducer.class);

        publisher = new DirectAuditPublisher(baseProperties, objectMapper, properties,
                new com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation(
                        io.micrometer.tracing.Tracer.NOOP,
                        io.micrometer.tracing.propagation.Propagator.NOOP));
        // Bypass @PostConstruct - we inject the producer directly
        // because we don't want the test to talk to a real broker.
        injectField(publisher, "session", session);
        injectField(publisher, "producer", producer);
    }

    @org.junit.jupiter.api.Test
    void publishesUpsertedAuditWithDirectModeAndJsonPayload() throws Exception {
        publisher.publishAudit("orders/created/12345",
                CompactionService.Outcome.UPSERTED, 16);

        ArgumentCaptor<XMLMessage> msgCap = ArgumentCaptor.forClass(XMLMessage.class);
        ArgumentCaptor<Topic> destCap = ArgumentCaptor.forClass(Topic.class);
        verify(producer, times(1)).send(msgCap.capture(), destCap.capture());

        XMLMessage sent = msgCap.getValue();
        assertThat(sent.getDeliveryMode()).isEqualTo(DeliveryMode.DIRECT);
        assertThat(sent.getHTTPContentType()).isEqualTo("application/json");
        assertThat(destCap.getValue().getName())
                .isEqualTo("orders/created/12345/compacted-ack");

        // Loop-protection user property attached.
        SDTMap userProps = sent.getProperties();
        assertThat(userProps).isNotNull();
        assertThat(userProps.getBoolean(properties.getLoopProtectionHeader()))
                .isTrue();

        // Payload shape stable for downstream consumers.
        byte[] data = ((BytesMessage) sent).getData();
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = objectMapper.readValue(data, Map.class);
        assertThat(payload).containsEntry("topic", "orders/created/12345");
        assertThat(payload).containsEntry("outcome", "UPSERTED");
        assertThat(payload).containsEntry("sizeBytes", 16);
        assertThat(payload).containsKey("ingestTimestamp");
    }

    @Test
    void suppressesAuditForSkippedLoopOutcome() throws JCSMPException {
        publisher.publishAudit("orders/created/1",
                CompactionService.Outcome.SKIPPED_LOOP, 0);
        verify(producer, never()).send(any(XMLMessage.class), any(Topic.class));
    }

    @Test
    void emitsAuditForSkippedOutOfOrder() throws Exception {
        publisher.publishAudit("orders/created/1",
                CompactionService.Outcome.SKIPPED_OUT_OF_ORDER, 0);
        ArgumentCaptor<XMLMessage> msgCap = ArgumentCaptor.forClass(XMLMessage.class);
        verify(producer, times(1)).send(msgCap.capture(), any(Topic.class));
        byte[] data = ((BytesMessage) msgCap.getValue()).getData();
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = objectMapper.readValue(data, Map.class);
        assertThat(payload).containsEntry("outcome", "SKIPPED_OUT_OF_ORDER");
    }

    @Test
    void publishAuditDoesNothingWhenAuditDisabled() throws JCSMPException {
        properties.getAudit().setEnabled(false);
        publisher.publishAudit("orders/x",
                CompactionService.Outcome.UPSERTED, 4);
        verify(producer, never()).send(any(XMLMessage.class), any(Topic.class));
    }

    @Test
    void swallowsBrokerSendExceptionSoConsumerIsNeverBlocked() throws JCSMPException {
        // Simulate a transient broker outage during a publish.
        org.mockito.Mockito.doThrow(new JCSMPException("simulated"))
                .when(producer).send(any(XMLMessage.class), any(Topic.class));
        // The call must not throw - audit is fire-and-forget.
        publisher.publishAudit("orders/x",
                CompactionService.Outcome.UPSERTED, 4);
    }

    @Test
    void dropsAuditWhenTopicIsBlank() throws JCSMPException {
        publisher.publishAudit("",
                CompactionService.Outcome.UPSERTED, 4);
        publisher.publishAudit(null,
                CompactionService.Outcome.UPSERTED, 4);
        verify(producer, never()).send(any(XMLMessage.class), any(Topic.class));
    }

    private static void injectField(Object target, String fieldName, Object value) throws Exception {
        Field f = target.getClass().getDeclaredField(fieldName);
        f.setAccessible(true);
        f.set(target, value);
    }
}
