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
 * Translates the replay workflow's pass-through message (originally a
 * command JSON) into the actual replay event.
 *
 * <p>Dispatch by command type:
 * <ul>
 *   <li>{@code REPLAY} - rewrite payload + destination from the
 *       single matching record. The original command message is
 *       replaced with the rewritten replay message.</li>
 *   <li>{@code BULK_REPLAY} - delegate to {@link BulkReplayService},
 *       which fans out the matching records via a separate output
 *       binding. This interceptor's return message is the bulk-result
 *       summary published to
 *       {@code topic-compaction/replay/bulk-result}.</li>
 *   <li>{@code DELETE} - deferred to Phase 3.3; reaches us as a
 *       failure document for now.</li>
 * </ul>
 *
 * <p>If the command JSON is malformed or violates the schema, a small
 * JSON failure document is published on
 * {@code topic-compaction/replay/failed}.
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
