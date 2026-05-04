package com.solace.labs.mi.topiccompaction.api;

import com.solace.labs.mi.topiccompaction.kvstore.CaffeineKvStore;
import com.solace.labs.mi.topiccompaction.kvstore.CompactedRecord;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.kvstore.KvStoreProperties;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;
import java.util.Map;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class KvStoreControllerTest {

    private MockMvc mockMvc;
    private KvStore kvStore;

    @BeforeEach
    void setUp() {
        kvStore = new CaffeineKvStore(new KvStoreProperties());
        CompactionMetrics metrics = new CompactionMetrics(new SimpleMeterRegistry(), kvStore);
        KvStoreController controller = new KvStoreController(kvStore, metrics);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(
                        new MappingJackson2HttpMessageConverter(),
                        new ByteArrayHttpMessageConverter())
                .build();
    }

    @Test
    void getReturnsRawPayloadAndContentType() throws Exception {
        kvStore.put("orders.created.1", new CompactedRecord(
                "the-payload".getBytes(StandardCharsets.UTF_8),
                Map.of("content-type", "text/plain"),
                "orders/created/1", 100L, null));

        mockMvc.perform(get("/api/v1/kv/orders.created.1"))
                .andExpect(status().isOk())
                .andExpect(content().contentType("text/plain"))
                .andExpect(content().string("the-payload"))
                .andExpect(header().string("x-compacted-topic", "orders/created/1"));
    }

    @Test
    void getReturnsNotFoundForUnknownKey() throws Exception {
        mockMvc.perform(get("/api/v1/kv/nope"))
                .andExpect(status().isNotFound());
    }

    @Test
    void getMetaReturnsJsonWithBase64Payload() throws Exception {
        kvStore.put("k", new CompactedRecord(
                "abc".getBytes(StandardCharsets.UTF_8),
                Map.of("content-type", "text/plain"),
                "k", 100L, 200L));

        mockMvc.perform(get("/api/v1/kv/k/meta"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.key").value("k"))
                .andExpect(jsonPath("$.topic").value("k"))
                .andExpect(jsonPath("$.ingestTimestamp").value(100L))
                .andExpect(jsonPath("$.senderTimestamp").value(200L))
                .andExpect(jsonPath("$.sizeBytes").value(3))
                .andExpect(jsonPath("$.payloadBase64").value("YWJj"));
    }

    @Test
    void listKeysReturnsAllAndPrefixFilter() throws Exception {
        kvStore.put("orders/1", record("orders/1"));
        kvStore.put("orders/2", record("orders/2"));
        kvStore.put("invoices/1", record("invoices/1"));

        mockMvc.perform(get("/api/v1/kv"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.count").value(3));

        mockMvc.perform(get("/api/v1/kv?prefix=orders/"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.count").value(2))
                .andExpect(jsonPath("$.keys[*]")
                        .value(org.hamcrest.Matchers.everyItem(
                                org.hamcrest.Matchers.startsWith("orders/"))));
    }

    @Test
    void deleteRemovesKey() throws Exception {
        kvStore.put("k", record("k"));
        mockMvc.perform(delete("/api/v1/kv/k"))
                .andExpect(status().isNoContent());
        mockMvc.perform(get("/api/v1/kv/k"))
                .andExpect(status().isNotFound());
    }

    private static CompactedRecord record(String key) {
        return new CompactedRecord(
                "x".getBytes(StandardCharsets.UTF_8),
                Map.of("solace_destination", key),
                key, 100L, null);
    }
}
