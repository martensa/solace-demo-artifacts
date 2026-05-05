package com.solace.labs.mi.topiccompaction.command;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

/**
 * The JSON command envelope clients publish on the command queue to
 * drive the MI's replay (single + bulk), delete, and future flows.
 *
 * <p>Designed to be extensible: unknown {@code command} values are
 * rejected cleanly; the {@code options} map carries
 * forward-compatible parameters.
 *
 * <p>V1 supports {@link CommandType#REPLAY},
 * {@link CommandType#BULK_REPLAY}, and {@link CommandType#DELETE}.
 *
 * <p>Field semantics depend on the command:
 * <ul>
 *   <li>{@code REPLAY} - {@code key} required, {@code pattern} ignored</li>
 *   <li>{@code BULK_REPLAY} - {@code pattern} required, {@code key} ignored</li>
 *   <li>{@code DELETE} - {@code key} required, optional
 *       {@code options.cascade} pattern for bulk delete</li>
 * </ul>
 *
 * <p>Schema-level validation happens in
 * {@code command.CommandEventParser} before the JSON is mapped to
 * this record. The schema lives at
 * {@code src/main/resources/schemas/command-event-v1.json}.
 *
 * <pre>
 * {
 *   "command": "REPLAY",
 *   "key": "orders/created/12345",
 *   "options": {
 *     "destinationSuffix": "/compacted",
 *     "correlationId": "user-correlation-123",
 *     "includeOriginalHeaders": true
 *   }
 * }
 * </pre>
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
@JsonIgnoreProperties(ignoreUnknown = true)
public record CommandEvent(
        @JsonProperty("command") CommandType command,
        @JsonProperty("key") String key,
        @JsonProperty("pattern") String pattern,
        @JsonProperty("options") Map<String, Object> options
) {
    public CommandEvent {
        if (options == null) options = Map.of();
    }

    /** Backward-compat for tests that build events without a pattern. */
    public CommandEvent(CommandType command, String key,
                        Map<String, Object> options) {
        this(command, key, null, options);
    }

    public Object option(String name) {
        return options == null ? null : options.get(name);
    }

    public String stringOption(String name, String defaultValue) {
        Object v = option(name);
        return v == null ? defaultValue : v.toString();
    }

    public boolean booleanOption(String name, boolean defaultValue) {
        Object v = option(name);
        if (v instanceof Boolean b) return b;
        if (v == null) return defaultValue;
        return Boolean.parseBoolean(v.toString());
    }

    public int intOption(String name, int defaultValue) {
        Object v = option(name);
        if (v instanceof Number n) return n.intValue();
        if (v == null) return defaultValue;
        try {
            return Integer.parseInt(v.toString());
        } catch (NumberFormatException e) {
            return defaultValue;
        }
    }
}
