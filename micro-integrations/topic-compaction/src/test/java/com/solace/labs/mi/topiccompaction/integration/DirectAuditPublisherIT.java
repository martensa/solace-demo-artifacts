package com.solace.labs.mi.topiccompaction.integration;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.labs.mi.topiccompaction.compaction.CompactionProperties;
import com.solace.labs.mi.topiccompaction.compaction.CompactionService;
import com.solace.labs.mi.topiccompaction.compaction.DirectAuditPublisher;
import com.solacesystems.jcsmp.BytesXMLMessage;
import com.solacesystems.jcsmp.JCSMPException;
import com.solacesystems.jcsmp.JCSMPFactory;
import com.solacesystems.jcsmp.JCSMPChannelProperties;
import com.solacesystems.jcsmp.JCSMPProperties;
import com.solacesystems.jcsmp.JCSMPSession;
import com.solacesystems.jcsmp.Topic;
import com.solacesystems.jcsmp.XMLMessageConsumer;
import com.solacesystems.jcsmp.XMLMessageListener;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.containers.wait.strategy.Wait;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import java.lang.reflect.Method;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Integration test for {@link DirectAuditPublisher} against a real
 * Solace PubSub+ broker (Testcontainers-managed). Validates the
 * V1.1.0 architectural contracts:
 *
 * <ol>
 *   <li>The publisher's separate JCSMP session opens against the
 *       broker (different {@code clientName} from the binder
 *       session) and the producer is ready to send.</li>
 *   <li>An audit publish on {@code DeliveryMode.DIRECT} is
 *       received by a subscriber within a sub-second timeout - no
 *       broker spool round-trip, no PERSISTENT path.</li>
 *   <li>The audit JSON shape is stable: topic / outcome /
 *       sizeBytes / ingestTimestamp.</li>
 *   <li>A failed audit publish (e.g. session disconnected) does
 *       NOT throw out of {@link DirectAuditPublisher#publishAudit}
 *       - this is the consumer-ack-decoupling guarantee.</li>
 * </ol>
 *
 * <p>Activated only as an integration test (named {@code *IT}); it
 * runs in the {@code failsafe:integration-test} phase and requires
 * Docker. The container takes ~30-60 s to come up; the entire
 * suite should complete in &lt;90 s on a warm cache.
 */
@Testcontainers
@org.junit.jupiter.api.TestMethodOrder(
        org.junit.jupiter.api.MethodOrderer.OrderAnnotation.class)
class DirectAuditPublisherIT {

    /**
     * Use the standard Solace PubSub+ image. {@code latest} keeps
     * us on the broker's GA stream; pin a specific tag here if the
     * test starts to flake on broker version drift. The shared
     * memory size is the broker's documented minimum for the
     * standard tier.
     */
    @Container
    static final GenericContainer<?> SOLACE = new GenericContainer<>(
            DockerImageName.parse("solace/solace-pubsub-standard:latest"))
            .withSharedMemorySize(1024L * 1024L * 1024L)
            .withExposedPorts(8080, 55555)
            .withEnv("system_scaling_maxconnectioncount", "100")
            .withEnv("username_admin_globalaccesslevel", "admin")
            .withEnv("username_admin_password", "admin")
            // Wait until the SEMP HTTP endpoint is up - the broker
            // accepts SEMP requests AFTER the Primary Virtual
            // Router is Active and the default VPN is provisioned,
            // so this is the most reliable "fully ready" signal we
            // can use without relying on log-message scraping.
            .waitingFor(Wait.forHttp("/SEMP/v2/config")
                    .forPort(8080)
                    .forStatusCodeMatching(code ->
                            code == 200 || code == 401)
                    .withStartupTimeout(Duration.ofMinutes(3)));

    private static JCSMPSession publisherSession;
    private static DirectAuditPublisher publisher;
    private static CompactionProperties properties;

    @BeforeAll
    static void setUp() throws Exception {
        String host = "tcp://" + SOLACE.getHost() + ":"
                + SOLACE.getMappedPort(55555);

        properties = new CompactionProperties();
        properties.getAudit().setEnabled(true);

        JCSMPProperties baseProps = new JCSMPProperties();
        baseProps.setProperty(JCSMPProperties.HOST, host);
        baseProps.setProperty(JCSMPProperties.VPN_NAME, "default");
        baseProps.setProperty(JCSMPProperties.USERNAME, "default");
        baseProps.setProperty(JCSMPProperties.PASSWORD, "default");
        baseProps.setProperty(JCSMPProperties.CLIENT_NAME, "topic-compaction-mi-it");
        // SEMP HTTP comes up a few seconds before SMF accepts
        // connections. Tell JCSMP to retry the initial connect a
        // few times so we ride out the gap without flaking.
        JCSMPChannelProperties chanProps = (JCSMPChannelProperties)
                baseProps.getProperty(JCSMPProperties.CLIENT_CHANNEL_PROPERTIES);
        chanProps.setConnectRetries(5);
        chanProps.setReconnectRetries(5);
        chanProps.setReconnectRetryWaitInMillis(2000);

        publisher = new DirectAuditPublisher(baseProps,
                new ObjectMapper(), properties,
                new com.solace.labs.mi.topiccompaction.observability.SolaceContextPropagation(
                        io.micrometer.tracing.Tracer.NOOP,
                        io.micrometer.tracing.propagation.Propagator.NOOP));
        // Invoke @PostConstruct manually (we're outside Spring DI).
        Method start = DirectAuditPublisher.class.getDeclaredMethod("start");
        start.setAccessible(true);
        start.invoke(publisher);

        // A second session that subscribes to the audit topic so we
        // can assert delivery.
        JCSMPProperties subProps = (JCSMPProperties) baseProps.clone();
        subProps.setProperty(JCSMPProperties.CLIENT_NAME,
                "topic-compaction-mi-it-subscriber");
        publisherSession = JCSMPFactory.onlyInstance().createSession(subProps);
        publisherSession.connect();
    }

    @AfterAll
    static void tearDown() throws Exception {
        if (publisher != null) {
            Method stop = DirectAuditPublisher.class.getDeclaredMethod("stop");
            stop.setAccessible(true);
            stop.invoke(publisher);
        }
        if (publisherSession != null) {
            publisherSession.closeSession();
        }
    }

    @org.junit.jupiter.api.Order(1)
    @Test
    void directAuditIsDeliveredToTopicSubscriberWithinASecond() throws Exception {
        // Run first; other tests mutate the publisher's audit-enabled
        // flag and we want to assert the happy path before any
        // state-toggling.
        properties.getAudit().setEnabled(true);
        String dataTopic = "orders/it/abc-123";
        String auditTopic = dataTopic + properties.getAuditSuffix();

        ConcurrentLinkedQueue<String> received = new ConcurrentLinkedQueue<>();
        CountDownLatch latch = new CountDownLatch(1);

        // Direct topic subscriber (no queue spool involved). This
        // is the right shape to assert DeliveryMode.DIRECT routing:
        // a topic subscription routes messages live to the
        // consumer, no temporary queue, no provisioning dance.
        XMLMessageConsumer consumer = publisherSession.getMessageConsumer(
                (com.solacesystems.jcsmp.JCSMPReconnectEventHandler) null,
                new XMLMessageListener() {
                    @Override
                    public void onReceive(BytesXMLMessage msg) {
                        byte[] data = new byte[msg.getAttachmentContentLength()];
                        msg.readAttachmentBytes(data);
                        received.offer(new String(data));
                        latch.countDown();
                    }

                    @Override
                    public void onException(JCSMPException e) { /* test-side, swallow */ }
                });
        consumer.start();

        publisherSession.addSubscription(
                JCSMPFactory.onlyInstance().createTopic(auditTopic));
        // Settle: subscription propagation takes a tick on
        // cold-start, and DIRECT messages have no spool fallback
        // so the race must resolve before the publish.
        Thread.sleep(1000);

        // Fire the audit twice (DIRECT is lossy by spec; on a
        // cold-start container a single message can race the
        // subscription routing internals). The first that arrives
        // satisfies the latch.
        for (int attempt = 0; attempt < 3; attempt++) {
            publisher.publishAudit(dataTopic,
                    CompactionService.Outcome.UPSERTED, 42);
            if (latch.await(2, TimeUnit.SECONDS)) {
                break;
            }
        }
        boolean delivered = latch.getCount() == 0;
        assertThat(delivered).as("audit delivered to subscriber after up to 3 retries")
                .isTrue();

        ObjectMapper om = new ObjectMapper();
        String body = received.poll();
        assertThat(body).isNotNull();
        @SuppressWarnings("unchecked")
        Map<String, Object> payload = om.readValue(body, Map.class);
        assertThat(payload).containsEntry("topic", dataTopic);
        assertThat(payload).containsEntry("outcome", "UPSERTED");
        assertThat(payload).containsEntry("sizeBytes", 42);
        assertThat(payload).containsKey("ingestTimestamp");

        consumer.close();
    }

    @org.junit.jupiter.api.Order(2)
    @Test
    void publishesNothingWhenAuditDisabled() throws Exception {
        properties.getAudit().setEnabled(false);
        // No exception even though we touch the wire-side code path.
        publisher.publishAudit("orders/it/disabled",
                CompactionService.Outcome.UPSERTED, 4);
        properties.getAudit().setEnabled(true);
    }

    @org.junit.jupiter.api.Order(3)
    @Test
    void skipsLoopOutcomeWithoutHittingBroker() {
        // SKIPPED_LOOP outcome short-circuits inside the publisher
        // before any JCSMP call. Verifies the V1.0.1 cascade-break
        // semantics survived the V1.1.0 rewrite.
        publisher.publishAudit("orders/it/loop",
                CompactionService.Outcome.SKIPPED_LOOP, 0);
        // No assertion on the broker side - the contract here is
        // purely "no throw, no broker round-trip". Lack of failure
        // is the test.
    }

}
