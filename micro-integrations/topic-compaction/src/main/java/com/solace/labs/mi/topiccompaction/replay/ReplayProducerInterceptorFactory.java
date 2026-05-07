package com.solace.labs.mi.topiccompaction.replay;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptorFactory;
import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.command.CommandEventParser;
import com.solace.labs.mi.topiccompaction.command.CommandType;
import com.solace.labs.mi.topiccompaction.delete.DeleteCommandService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.BinderHeaders;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.GenericMessage;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * V1.1.1: builds the actual REPLAY message for the binder to publish
 * on {@code <key>/compacted}. Other command types (BULK_REPLAY,
 * DELETE, parse-failure) no longer reach this interceptor - they
 * are intercepted on the consumer side by
 * {@link CommandConsumerInterceptorFactory} and short-circuit the
 * workflow output via a {@code null} return on the consumer
 * channel. This is the same architectural pattern V1.1.0 applied
 * to compaction: any command whose summary publish would gate the
 * inbound consumer-ack on a fire-and-forget observability publish
 * needs to short-circuit the binder publish path entirely.
 *
 * <p>For SINGLE REPLAY the binder publish path is preserved because
 * the replay event is durability-relevant: operators are expected
 * to have a queue subscribed to {@code <key>/compacted} (or its
 * configured suffix). A genuinely missing subscriber will still
 * cause the broker to discard the publish silently and the command
 * will redeliver up to {@code maxRedeliveryCount=5} before being
 * routed to {@code #DEAD_MSG_QUEUE}; that's the right operator
 * signal.
 */
@Component
public class ReplayProducerInterceptorFactory
        implements ProducerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(
            ReplayProducerInterceptorFactory.class);
    private static final String SOLACE_DESTINATION_HEADER =
            "solace_destination";
    private static final String FAILURE_DESTINATION =
            "topic-compaction/replay/failed";
    private static final String BULK_RESULT_DESTINATION =
            "topic-compaction/replay/bulk-result";
    private static final String DELETE_RESULT_DESTINATION =
            "topic-compaction/delete/result";

    private final ReplayService replayService;
    private final BulkReplayService bulkReplayService;
    private final DeleteCommandService deleteCommandService;
    private final CommandEventParser parser;
    private final ObjectMapper objectMapper;
    private final ReplayProperties properties;
    private final Set<String> outputBindingNames;

    public ReplayProducerInterceptorFactory(
            ReplayService replayService,
            BulkReplayService bulkReplayService,
            DeleteCommandService deleteCommandService,
            CommandEventParser parser,
            ObjectMapper objectMapper,
            ReplayProperties properties) {
        this.replayService = replayService;
        this.bulkReplayService = bulkReplayService;
        this.deleteCommandService = deleteCommandService;
        this.parser = parser;
        this.objectMapper = objectMapper;
        this.properties = properties;
        // Symmetric mapping: input-N -> output-N
        this.outputBindingNames = new HashSet<>();
        for (String input : properties.getBindingNames()) {
            if (input.startsWith("input-")) {
                outputBindingNames.add("output-"
                        + input.substring("input-".length()));
            }
        }
    }

    @Override
    @Nullable
    public ProducerBindingMessageInterceptor createIfNecessary(
            String binderType, ProducerProperties producerProperties) {
        if (!"solace".equals(binderType)) {
            return null;
        }
        String bindingName = producerProperties.getBindingName();
        if (!outputBindingNames.contains(bindingName)) {
            return null;
        }
        log.info("Attaching ReplayInterceptor to Solace producer "
                + "binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor
            implements ProducerBindingMessageInterceptor {

        @Override
        public Message<?> before(Message<?> message) {
            byte[] commandBytes = bytesFrom(message);
            CommandEvent event;
            try {
                event = parser.parse(commandBytes);
            } catch (CommandEventParser.ParseException e) {
                // V1.1.1: parse failures are normally caught by the
                // CommandConsumerInterceptor and short-circuited
                // before reaching this point. Reaching here means
                // either operator config has disabled the consumer
                // interceptor or someone bypassed the workflow with
                // StreamBridge - either way emit the failure doc.
                return failure(e.getMessage());
            }
            return switch (event.command()) {
                case REPLAY -> handleSingleReplay(event);
                case BULK_REPLAY -> handleBulkReplay(event);
                case DELETE -> handleDelete(event);
            };
        }

        private Message<?> handleSingleReplay(CommandEvent event) {
            ReplayService.Decision decision = replayService.process(event);
            if (!decision.success()) {
                log.warn("Replay command failed: {}", decision.failure());
                return failure(decision.failure());
            }
            Map<String, Object> headers =
                    new LinkedHashMap<>(decision.headers());
            // Set both destination header conventions; different
            // Solace binder versions read different ones.
            headers.putIfAbsent(BinderHeaders.TARGET_DESTINATION,
                    decision.destination());
            return new GenericMessage<>(decision.payload(), headers);
        }

        private Message<?> handleBulkReplay(CommandEvent event) {
            BulkReplayService.BulkResult result =
                    bulkReplayService.execute(event);
            if (!result.isSuccess()) {
                log.warn("BulkReplay rejected: {}", result.error());
                return failure(result.error());
            }
            return summary(result, event);
        }

        private Message<?> handleDelete(CommandEvent event) {
            DeleteCommandService.DeleteResult result =
                    deleteCommandService.execute(event);
            if (!result.isSuccess()) {
                log.warn("Delete command rejected: {}", result.error());
                return failure(result.error());
            }
            return deleteSummary(result, event);
        }

        private Message<?> failure(String reason) {
            Map<String, Object> headers = new LinkedHashMap<>();
            headers.put(SOLACE_DESTINATION_HEADER, FAILURE_DESTINATION);
            headers.put(BinderHeaders.TARGET_DESTINATION,
                    FAILURE_DESTINATION);
            headers.put("content-type", "application/json");
            byte[] body = renderJson(Map.of(
                    "status", "failed",
                    "reason", reason,
                    "timestamp", System.currentTimeMillis()));
            return new GenericMessage<>(body, headers);
        }

        private Message<?> summary(
                BulkReplayService.BulkResult result,
                CommandEvent event) {
            Map<String, Object> headers = new LinkedHashMap<>();
            headers.put(SOLACE_DESTINATION_HEADER,
                    BULK_RESULT_DESTINATION);
            headers.put(BinderHeaders.TARGET_DESTINATION,
                    BULK_RESULT_DESTINATION);
            headers.put("content-type", "application/json");
            String correlationId = event.stringOption(
                    "correlationId", null);
            if (correlationId != null) {
                headers.put("x-original-correlation-id",
                        correlationId);
            }
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("status", "completed");
            body.put("pattern", result.pattern());
            body.put("matched", result.matched());
            body.put("replayed", result.replayed());
            body.put("failed", result.failed());
            body.put("durationMs", result.durationMs());
            if (correlationId != null) {
                body.put("correlationId", correlationId);
            }
            return new GenericMessage<>(renderJson(body), headers);
        }

        private Message<?> deleteSummary(
                DeleteCommandService.DeleteResult result,
                CommandEvent event) {
            Map<String, Object> headers = new LinkedHashMap<>();
            headers.put(SOLACE_DESTINATION_HEADER,
                    DELETE_RESULT_DESTINATION);
            headers.put(BinderHeaders.TARGET_DESTINATION,
                    DELETE_RESULT_DESTINATION);
            headers.put("content-type", "application/json");
            String correlationId = event.stringOption(
                    "correlationId", null);
            if (correlationId != null) {
                headers.put("x-original-correlation-id",
                        correlationId);
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
            if (correlationId != null) {
                body.put("correlationId", correlationId);
            }
            return new GenericMessage<>(renderJson(body), headers);
        }

        private byte[] renderJson(Map<String, Object> doc) {
            try {
                return objectMapper.writeValueAsBytes(doc);
            } catch (JsonProcessingException e) {
                return ("{\"status\":\"failed\","
                        + "\"reason\":\"json render error\"}")
                        .getBytes(StandardCharsets.UTF_8);
            }
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
