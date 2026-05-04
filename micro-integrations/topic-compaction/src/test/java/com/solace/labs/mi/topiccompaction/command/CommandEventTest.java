package com.solace.labs.mi.topiccompaction.command;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class CommandEventTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void parsesMinimalReplayCommand() throws Exception {
        String json = """
                {
                  "command": "REPLAY",
                  "key": "orders/created/12345"
                }
                """;
        CommandEvent event = objectMapper.readValue(json, CommandEvent.class);
        assertThat(event.command()).isEqualTo(CommandType.REPLAY);
        assertThat(event.key()).isEqualTo("orders/created/12345");
        assertThat(event.options()).isEmpty();
    }

    @Test
    void parsesCommandWithOptions() throws Exception {
        String json = """
                {
                  "command": "replay",
                  "key": "orders/1",
                  "options": {
                    "destinationSuffix": "/replayed",
                    "correlationId": "abc-123",
                    "includeOriginalHeaders": false
                  }
                }
                """;
        CommandEvent event = objectMapper.readValue(json, CommandEvent.class);
        assertThat(event.command()).isEqualTo(CommandType.REPLAY);
        assertThat(event.stringOption("destinationSuffix", null)).isEqualTo("/replayed");
        assertThat(event.stringOption("correlationId", null)).isEqualTo("abc-123");
        assertThat(event.booleanOption("includeOriginalHeaders", true)).isFalse();
    }

    @Test
    void rejectsUnknownCommand() {
        String json = """
                { "command": "UNKNOWN", "key": "x" }
                """;
        assertThatThrownBy(() -> objectMapper.readValue(json, CommandEvent.class))
                .hasRootCauseInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown command");
    }

    @Test
    void ignoresUnknownTopLevelFieldsForForwardCompatibility() throws Exception {
        // Future versions may add more fields - clients on older MI versions must keep working.
        String json = """
                {
                  "command": "REPLAY",
                  "key": "k",
                  "futureField": "ignored"
                }
                """;
        CommandEvent event = objectMapper.readValue(json, CommandEvent.class);
        assertThat(event.command()).isEqualTo(CommandType.REPLAY);
    }

    @Test
    void booleanOptionFallsBackToDefaultWhenAbsent() {
        CommandEvent event = new CommandEvent(CommandType.REPLAY, "k", null);
        assertThat(event.booleanOption("missing", true)).isTrue();
        assertThat(event.booleanOption("missing", false)).isFalse();
    }
}
