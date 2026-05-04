package com.solace.labs.mi.topiccompaction.kvstore;

import java.util.Map;
import java.util.Objects;

/**
 * A single compacted entry: the latest message seen for a given topic, plus metadata.
 *
 * <p>Stored in the KV store keyed by the original topic string.
 *
 * @param payload           raw message payload bytes
 * @param headers           message headers (Solace user-properties + framework headers)
 * @param originalTopic     the topic on which the message was originally published
 * @param ingestTimestamp   epoch millis at which this MI received the message
 * @param senderTimestamp   optional sender-supplied timestamp (epoch millis) used for
 *                          out-of-order detection; null when not supplied
 */
public record CompactedRecord(
        byte[] payload,
        Map<String, Object> headers,
        String originalTopic,
        long ingestTimestamp,
        Long senderTimestamp
) {
    public CompactedRecord {
        Objects.requireNonNull(payload, "payload");
        Objects.requireNonNull(originalTopic, "originalTopic");
        if (headers == null) headers = Map.of();
    }

    public int sizeBytes() {
        return payload.length;
    }
}
