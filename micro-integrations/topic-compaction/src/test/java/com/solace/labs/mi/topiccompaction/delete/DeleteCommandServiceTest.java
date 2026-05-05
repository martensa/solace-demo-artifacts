package com.solace.labs.mi.topiccompaction.delete;

import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.command.CommandType;
import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class DeleteCommandServiceTest {

    private KvStore kvStore;
    private DeleteCommandService service;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        service = new DeleteCommandService(kvStore,
                new CompactionMetrics(
                        new SimpleMeterRegistry(), kvStore));
    }

    @Test
    void singleDeleteRemovesRecord() {
        seed("orders/A");
        DeleteCommandService.DeleteResult result = service.execute(
                deleteCommand("orders/A", null));

        assertThat(result.isSuccess()).isTrue();
        assertThat(result.singleDeleted()).isTrue();
        assertThat(kvStore.get("orders/A")).isEmpty();
    }

    @Test
    void deleteOfMissingKeyIsIdempotent() {
        DeleteCommandService.DeleteResult result = service.execute(
                deleteCommand("never-existed", null));

        assertThat(result.isSuccess()).isTrue();
        assertThat(result.singleDeleted()).isFalse();
    }

    @Test
    void cascadeDeletesAllMatching() {
        seed("orders/A");
        seed("orders/B");
        seed("orders/C");
        seed("invoices/X");

        DeleteCommandService.DeleteResult result = service.execute(
                deleteCommand("orders/A", "orders/*"));

        assertThat(result.isSuccess()).isTrue();
        assertThat(result.singleDeleted()).isTrue();
        assertThat(result.cascadeMatched()).isEqualTo(3);
        assertThat(result.cascadeDeleted()).isEqualTo(3);
        assertThat(kvStore.get("invoices/X")).isPresent();
        assertThat(kvStore.get("orders/A")).isEmpty();
        assertThat(kvStore.get("orders/B")).isEmpty();
        assertThat(kvStore.get("orders/C")).isEmpty();
    }

    @Test
    void cascadeMultiLevelWildcardOnSubtree() {
        seed("orders/created/A");
        seed("orders/created/A/B");
        seed("orders/created/A/B/C");
        seed("orders/updated/X");

        // orders/created/A/> matches A/B and A/B/C but NOT A itself
        // ('>' requires one-or-more additional levels). The explicit
        // key=A is then deleted via the single-delete path.
        DeleteCommandService.DeleteResult result = service.execute(
                deleteCommand("orders/created/A",
                        "orders/created/A/>"));

        assertThat(result.isSuccess()).isTrue();
        assertThat(result.singleDeleted()).isTrue();
        assertThat(result.cascadeMatched()).isEqualTo(2);
        assertThat(result.cascadeDeleted()).isEqualTo(2);
        assertThat(kvStore.get("orders/created/A")).isEmpty();
        assertThat(kvStore.get("orders/created/A/B")).isEmpty();
        assertThat(kvStore.get("orders/created/A/B/C")).isEmpty();
        assertThat(kvStore.get("orders/updated/X")).isPresent();
    }

    @Test
    void rejectsMissingKey() {
        DeleteCommandService.DeleteResult result = service.execute(
                deleteCommand(null, null));

        assertThat(result.isSuccess()).isFalse();
        assertThat(result.error()).contains("key is required");
    }

    @Test
    void rejectsInvalidCascadePattern() {
        seed("orders/A");
        DeleteCommandService.DeleteResult result = service.execute(
                deleteCommand("orders/A", "orders/>/created"));

        assertThat(result.isSuccess()).isFalse();
        assertThat(result.error()).contains("Invalid cascade pattern");
    }

    private void seed(String key) {
        kvStore.put(key, new CompactedRecord(
                "x".getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", key),
                key, 100L, null));
    }

    private static CommandEvent deleteCommand(
            String key, String cascade) {
        Map<String, Object> options = cascade == null
                ? Map.of()
                : Map.of("cascade", cascade);
        return new CommandEvent(CommandType.DELETE,
                key, null, options);
    }
}
