package com.solace.labs.mi.topiccompaction.command;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Parses command-event JSON, validating it against the JSON Schema
 * at {@code classpath:schemas/command-event-v1.json} before mapping
 * to a {@link CommandEvent}.
 *
 * <p>Two failure modes:
 * <ul>
 *   <li>Schema violation: surface a {@link ParseException} with a
 *       structured violation list. The replay interceptor turns this
 *       into a fail-event published to
 *       {@code topic-compaction/replay/failed}.</li>
 *   <li>Jackson mapping error (malformed JSON, type mismatch): also
 *       surfaced as {@link ParseException}. Schema validation catches
 *       most of these; this branch is the safety net for edge cases
 *       like trailing garbage.</li>
 * </ul>
 */
@Component
public class CommandEventParser {

    private final ObjectMapper objectMapper;
    private final Resource schemaResource;
    private JsonSchema schema;

    public CommandEventParser(
            ObjectMapper objectMapper,
            @Value("classpath:schemas/command-event-v1.json")
            Resource schemaResource) {
        this.objectMapper = objectMapper;
        this.schemaResource = schemaResource;
    }

    @PostConstruct
    public void init() throws IOException {
        SchemaValidatorsConfig config = new SchemaValidatorsConfig();
        config.setFailFast(false);
        try (InputStream in = schemaResource.getInputStream()) {
            JsonSchemaFactory factory = JsonSchemaFactory.getInstance(
                    SpecVersion.VersionFlag.V202012);
            this.schema = factory.getSchema(in, config);
        }
    }

    /**
     * Parse the command JSON. Throws {@link ParseException} if the
     * JSON is malformed or violates the schema.
     */
    public CommandEvent parse(byte[] commandJson) {
        JsonNode tree;
        try {
            tree = objectMapper.readTree(commandJson);
        } catch (IOException e) {
            throw new ParseException("Invalid JSON: " + e.getMessage());
        }

        Set<ValidationMessage> errors = schema.validate(tree);
        if (!errors.isEmpty()) {
            String detail = errors.stream()
                    .map(ValidationMessage::getMessage)
                    .collect(Collectors.joining("; "));
            throw new ParseException("Schema violation: " + detail);
        }

        try {
            return objectMapper.treeToValue(tree, CommandEvent.class);
        } catch (Exception e) {
            // Schema validation should have caught structural issues;
            // this is a safety net for value coercion edge cases.
            throw new ParseException(
                    "Mapping error: " + e.getMessage());
        }
    }

    /** Thrown when a command JSON cannot be turned into a {@link CommandEvent}. */
    public static class ParseException extends RuntimeException {
        public ParseException(String message) {
            super(message);
        }
    }
}
