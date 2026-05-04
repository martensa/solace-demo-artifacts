package com.solace.labs.mi.topiccompaction.command;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

/**
 * The JSON command envelope clients publish on the command queue to drive the
 * MI's replay (and, in future versions, delete / bulk operations).
 *
 * <p>Designed to be extensible: unknown {@code command} values are rejected
 * cleanly; the {@code options} map carries forward-compatible parameters.
 *
 * <p>V1 supports {@code REPLAY}. V2 roadmap: {@code DELETE}, {@code BULK_REPLAY}.
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
        @JsonProperty("options") Map<String, Object> options
) {
    public CommandEvent {
        if (options == null) options = Map.of();
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
}
