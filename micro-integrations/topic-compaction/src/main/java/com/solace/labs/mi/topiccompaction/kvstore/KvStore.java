package com.solace.labs.mi.topiccompaction.kvstore;

import java.util.Optional;
import java.util.stream.Stream;

/**
 * Backend-agnostic key-value store for compacted topic state.
 *
 * <p>Implementations must be thread-safe; the MI may invoke put/get from multiple
 * Solace consumer threads concurrently.
 */
public interface KvStore {

    /**
     * Insert or replace the record for {@code key}.
     */
    void put(String key, CompactedRecord record);

    /**
     * Look up the latest record for {@code key}.
     */
    Optional<CompactedRecord> get(String key);

    /**
     * Remove the record for {@code key}. No-op if absent.
     */
    void delete(String key);

    /**
     * Approximate count of entries currently stored.
     */
    long size();

    /**
     * Stream all keys whose string starts with the given prefix. Pass an empty
     * string to stream every key. Caller must close the stream.
     */
    Stream<String> keys(String prefix);
}
