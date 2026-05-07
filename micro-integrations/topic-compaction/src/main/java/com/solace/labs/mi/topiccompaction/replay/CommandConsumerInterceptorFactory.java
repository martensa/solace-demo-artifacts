package com.solace.labs.mi.topiccompaction.replay;

import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ConsumerBindingMessageInterceptorFactory;
import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.command.CommandEventParser;
import com.solace.labs.mi.topiccompaction.compaction.DirectAuditPublisher;
import com.solace.labs.mi.topiccompaction.delete.DeleteCommandService;
import com.solace.labs.mi.topiccompaction.util.AckHelper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.BinderHeaders;
import org.springframework.cloud.stream.binder.ConsumerProperties;
import org.springframework.cloud.stream.function.StreamBridge;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * V1.1.1: handles BULK_REPLAY, DELETE, and parse-failure command
 * events on the CONSUMER side of the workflow, returning {@code null}
 * to suppress the workflow's downstream output channel send.
 *
 * <p>The motivation is the same as the V1.1.0 fix on the compaction
 * path: the MI Framework's {@code AsyncOutputSendingMessageHandler}
 * chains the consumer-ack on the inbound command to the publish-ack
 * of the workflow's output. For command events that emit a SUMMARY
 * to a topic ({@code topic-compaction/replay/bulk-result},
 * {@code topic-compaction/delete/result},
 * {@code topic-compaction/replay/failed}) where typically no
 * persistent subscriber is provisioned, the broker silently
 * discards the publish ({@code msgSpoolRxDiscardedMsgCount}
 * increments), no NACK fires, the consumer-ack pinned in
 * {@code txUnackedMsgCount} until the framework's
 * {@code publish-timeout} fires - and the command is then
 * redelivered, re-running the whole bulk replay or delete.
 *
 * <p>The fix: do the work in a Spring Integration
 * {@code ChannelInterceptor#preSend}-shaped consumer interceptor,
 * fire the summary as a fire-and-forget DIRECT message via the
 * separate-session {@link DirectAuditPublisher}, and return null
 * from {@code after()} so the workflow's output channel is never
 * touched. The inbound consumer-ack flushes as soon as this method
 * returns.
 *
 * <p>The {@link CommandType#REPLAY} branch is intentionally left
 * for the existing {@link ReplayProducerInterceptorFactory}: a
 * single-key replay genuinely wants PERSISTENT delivery on
 * {@code <key>/compacted} and operators are expected to subscribe
 * a queue to that topic. We pass the message through unchanged so
 * the producer interceptor builds and publishes the replay event
 * via the binder's normal path. (The same broker-discard scenario
 * applies if no subscriber is provisioned; that is the operator's
 * responsibility, not the MI's.)
 */
@Component
public class CommandConsumerInterceptorFactory
        implements ConsumerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(
            CommandConsumerInterceptorFactory.class);

    static final String BULK_RESULT_DESTINATION =
            "topic-compaction/replay/bulk-result";
    static final String DELETE_RESULT_DESTINATION =
            "topic-compaction/delete/result";
    static final String FAILURE_DESTINATION =
            "topic-compaction/replay/failed";

    private final CommandEventParser parser;
    private final ReplayService replayService;
    private final BulkReplayService bulkReplayService;
    private final DeleteCommandService deleteCommandService;
    private final DirectAuditPublisher publisher;
    private final StreamBridge streamBridge;
    private final ReplayProperties properties;

    public CommandConsumerInterceptorFactory(
            CommandEventParser parser,
            ReplayService replayService,
            BulkReplayService bulkReplayService,
            DeleteCommandService deleteCommandService,
            DirectAuditPublisher publisher,
            StreamBridge streamBridge,
            ReplayProperties properties) {
        this.parser = parser;
        this.replayService = replayService;
        this.bulkReplayService = bulkReplayService;
        this.deleteCommandService = deleteCommandService;
        this.publisher = publisher;
        this.streamBridge = streamBridge;
        this.properties = properties;
    }

    @Override
    @Nullable
    public ConsumerBindingMessageInterceptor createIfNecessary(
            String binderType, ConsumerProperties consumerProperties) {
        if (!"solace".equals(binderType)) {
            return null;
        }
        String bindingName = consumerProperties.getBindingName();
        if (!properties.getBindingNames().contains(bindingName)) {
            return null;
        }
        log.info("Attaching CommandConsumerInterceptor to Solace consumer "
                + "binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor implements ConsumerBindingMessageInterceptor {

        @Override
        public Message<?> after(Message<?> message) {
            byte[] commandBytes = bytesFrom(message);
            CommandEvent event;
            try {
                event = parser.parse(commandBytes);
            } catch (CommandEventParser.ParseException e) {
                // Parse-failure: fire failure doc fire-and-forget,
                // manually ACK the inbound, then drop the message.
                publishFailure(e.getMessage(), null);
                AckHelper.accept(message);
                return null;
            }

            switch (event.command()) {
                case REPLAY:
                    handleSingleReplay(event);
                    AckHelper.accept(message);
                    return null;
                case BULK_REPLAY:
                    handleBulkReplay(event);
                    AckHelper.accept(message);
                    return null;
                case DELETE:
                    handleDelete(event);
                    AckHelper.accept(message);
                    return null;
                default:
                    throw new IllegalStateException(
                            "Unknown command: " + event.command());
            }
        }

        /**
         * V1.1.3: SINGLE REPLAY now also goes through the consumer-
         * side path. We use {@link StreamBridge} to publish to the
         * fan-out binding ({@code output-3}, the same binding
         * BulkReplayService already uses), which is fire-and-forget
         * from the consumer's perspective. The command-ack is
         * flushed via AckHelper independently of whether the
         * downstream broker spool succeeded.
         *
         * <p>Earlier versions left REPLAY on the workflow's output-1
         * binding under the assumption that an operator would have
         * a guaranteed subscriber on {@code <key>/compacted}. In
         * practice the typical TryMe / live-debug subscriber is
         * DIRECT-only, so the broker silently discards the PERSISTENT
         * publish, the publish-ack callback never fires, and the
         * inbound command redelivers. The user observes the same
         * replay payload arriving repeatedly on {@code <key>/compacted}
         * because each redelivery re-runs the lookup-and-publish.
         */
        private void handleSingleReplay(CommandEvent event) {
            ReplayService.Decision decision = replayService.process(event);
            if (!decision.success()) {
                log.warn("Replay command failed: {}", decision.failure());
                publishFailure(decision.failure(),
                        event.stringOption("correlationId", null));
                return;
            }
            MessageBuilder<byte[]> b = MessageBuilder
                    .withPayload(decision.payload());
            decision.headers().forEach((k, v) -> {
                if (v != null) {
                    b.setHeader(k, v);
                }
            });
            b.setHeader("solace_destination", decision.destination());
            b.setHeader(BinderHeaders.TARGET_DESTINATION,
                    decision.destination());
            String correlationId = event.stringOption(
                    "correlationId", null);
            if (correlationId != null) {
                b.setHeader("x-original-correlation-id", correlationId);
            }
            try {
                streamBridge.send(BulkReplayService.FANOUT_BINDING,
                        b.build());
            } catch (RuntimeException e) {
                log.error("Replay: StreamBridge send failed for key={}: {}",
                        event.key(), e.getMessage());
                publishFailure("StreamBridge send failed: " + e.getMessage(),
                        correlationId);
            }
        }

        /**
         * Run the bulk replay (fanout via output-3 StreamBridge),
         * fire the summary fire-and-forget, return null so the
         * consumer-ack is decoupled.
         */
        private Message<?> handleBulkReplay(CommandEvent event) {
            BulkReplayService.BulkResult result =
                    bulkReplayService.execute(event);
            if (!result.isSuccess()) {
                log.warn("BulkReplay rejected: {}", result.error());
                publishFailure(result.error(),
                        event.stringOption("correlationId", null));
                return null;
            }
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "completed");
            body.put("pattern", result.pattern());
            body.put("matched", result.matched());
            body.put("replayed", result.replayed());
            body.put("failed", result.failed());
            body.put("durationMs", result.durationMs());
            String correlationId = event.stringOption("correlationId", null);
            if (correlationId != null) {
                body.put("correlationId", correlationId);
            }
            publisher.publishJsonDirect(BULK_RESULT_DESTINATION,
                    body, correlationId);
            return null;
        }

        /**
         * Run the delete, fire the summary fire-and-forget, return
         * null so the consumer-ack is decoupled.
         */
        private Message<?> handleDelete(CommandEvent event) {
            DeleteCommandService.DeleteResult result =
                    deleteCommandService.execute(event);
            if (!result.isSuccess()) {
                log.warn("Delete command rejected: {}", result.error());
                publishFailure(result.error(),
                        event.stringOption("correlationId", null));
                return null;
            }
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "completed");
            body.put("key", result.key());
            body.put("singleDeleted", result.singleDeleted());
            if (result.cascadePattern() != null) {
                body.put("cascadePattern", result.cascadePattern());
                body.put("cascadeMatched", result.cascadeMatched());
                body.put("cascadeDeleted", result.cascadeDeleted());
            }
            String correlationId = event.stringOption("correlationId", null);
            if (correlationId != null) {
                body.put("correlationId", correlationId);
            }
            publisher.publishJsonDirect(DELETE_RESULT_DESTINATION,
                    body, correlationId);
            return null;
        }

        private void publishFailure(String reason, String correlationId) {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "failed");
            body.put("reason", reason);
            body.put("timestamp", System.currentTimeMillis());
            if (correlationId != null) {
                body.put("correlationId", correlationId);
            }
            publisher.publishJsonDirect(FAILURE_DESTINATION,
                    body, correlationId);
        }
    }

    private static byte[] bytesFrom(Message<?> message) {
        Object payload = message.getPayload();
        if (payload instanceof byte[] b) return b;
        if (payload instanceof String s) {
            return s.getBytes(StandardCharsets.UTF_8);
        }
        return String.valueOf(payload)
                .getBytes(StandardCharsets.UTF_8);
    }
}
