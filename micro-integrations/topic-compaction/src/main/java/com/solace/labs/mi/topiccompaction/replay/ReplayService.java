package com.solace.labs.mi.topiccompaction.replay;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.command.CommandType;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.observation.annotation.Observed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Translates an inbound command event into a replay decision.
 *
 * <p>The {@link ReplayProducerInterceptorFactory producer interceptor} consults
 * this service for every message published from the replay workflow's output
 * binding. A {@link Decision} either provides a fully-rewritten replay message
 * (destination + payload + headers) or signals an error condition that should
 * surface to the dead-letter queue.
 */
@Service
public class ReplayService {

    private static final Logger log = LoggerFactory.getLogger(ReplayService.class);

    private final KvStore kvStore;
    private final ReplayProperties properties;
    private final ObjectMapper objectMapper;
    private final CompactionMetrics metrics;

    public ReplayService(KvStore kvStore,
                         ReplayProperties properties,
                         ObjectMapper objectMapper,
                         CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.metrics = metrics;
    }

    /**
     * Parse and act on a command JSON payload.
     *
     * <p>Wrapped in an {@link Observed} span so the JSON-parse cost
     * is visible in traces and a span exists even when the command
     * fails to parse.
     */
    @Observed(name = "replay.parse-and-process",
            contextualName = "replay-command",
            lowCardinalityKeyValues = {"workflow", "replay"})
    public Decision process(byte[] commandJson) {
        try (MDC.MDCCloseable ignored = MDC.putCloseable(
                "service", "replay")) {
            CommandEvent event;
            try {
                event = objectMapper.readValue(
                        commandJson, CommandEvent.class);
            } catch (Exception e) {
                return Decision.fail(
                        "Invalid command JSON: " + e.getMessage());
            }
            return processInternal(event);
        }
    }

    /**
     * Test-friendly entry point that takes a parsed command. Tests
     * call this directly to avoid round-tripping through Jackson.
     */
    public Decision process(CommandEvent event) {
        try (MDC.MDCCloseable ignored = MDC.putCloseable(
                "service", "replay")) {
            return processInternal(event);
        }
    }

    private Decision processInternal(CommandEvent event) {
        if (event.command() == null) {
            return Decision.fail("Command type is required");
        }
        if (event.key() == null || event.key().isBlank()) {
            return Decision.fail("Command key is required");
        }
        try (MDC.MDCCloseable ignoredKey = MDC.putCloseable(
                "key", event.key());
             MDC.MDCCloseable ignoredCmd = MDC.putCloseable(
                "command", event.command().name())) {

            if (event.command() != CommandType.REPLAY) {
                // V1 only handles REPLAY here. DELETE / BULK_REPLAY
                // are dispatched by their own services in later
                // phases.
                return Decision.fail(
                        "Command not supported in V1: " + event.command());
            }

            Optional<CompactedRecord> record = kvStore.get(event.key());
            if (record.isEmpty()) {
                log.info("Replay: no record found for key={}",
                        event.key());
                return Decision.fail(
                        "No record stored for key: " + event.key());
            }

            String suffix = event.stringOption(
                    "destinationSuffix", properties.getTargetSuffix());
            String destination = event.key() + suffix;
            boolean includeHeaders = event.booleanOption(
                    "includeOriginalHeaders", true);
            String correlationId = event.stringOption(
                    "correlationId", null);

            Map<String, Object> headers = new LinkedHashMap<>();
            if (includeHeaders) {
                headers.putAll(record.get().headers());
            }
            // Always rewrite the destination headers and inject
            // loop-protection.
            headers.put("solace_destination", destination);
            headers.put(properties.getLoopProtectionHeader(), true);
            if (correlationId != null) {
                headers.put("x-original-correlation-id", correlationId);
            }
            headers.put("x-compaction-replay-source-key", event.key());

            metrics.recordReplay();
            log.info("Replay: prepared message for key={} "
                    + "-> destination={} ({} bytes)",
                    event.key(), destination,
                    record.get().payload().length);

            return Decision.success(destination,
                    record.get().payload(), headers);
        }
    }

    /**
     * Render a small JSON document explaining a failure - useful as the body of
     * an error event published to the workflow's DLQ.
     */
    public byte[] renderFailureDocument(String reason) {
        Map<String, Object> doc = new LinkedHashMap<>();
        doc.put("status", "failed");
        doc.put("reason", reason);
        doc.put("timestamp", System.currentTimeMillis());
        try {
            return objectMapper.writeValueAsBytes(doc);
        } catch (JsonProcessingException e) {
            return ("{\"status\":\"failed\",\"reason\":\"" + reason.replace("\"", "'") + "\"}")
                    .getBytes(StandardCharsets.UTF_8);
        }
    }

    /**
     * Outcome of one command-event processing call.
     *
     * @param success     true if the lookup succeeded and a replay should be emitted
     * @param destination the rewritten destination (only when success)
     * @param payload     the payload to publish (only when success)
     * @param headers     the headers to set on the outbound message (only when success)
     * @param failure     human-readable failure reason (only when not success)
     */
    public record Decision(boolean success,
                           String destination,
                           byte[] payload,
                           Map<String, Object> headers,
                           String failure) {

        public static Decision success(String destination, byte[] payload, Map<String, Object> headers) {
            return new Decision(true, destination, payload, headers, null);
        }

        public static Decision fail(String reason) {
            return new Decision(false, null, null, null, reason);
        }
    }
}
