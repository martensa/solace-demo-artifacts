package com.solace.labs.mi.topiccompaction.kvstore;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;

import java.util.Optional;
import java.util.stream.Stream;

/**
 * In-memory Caffeine-backed implementation of {@link KvStore}.
 *
 * <p>Used primarily for tests and dev environments. Not persistent.
 */
public class CaffeineKvStore implements KvStore {

    private final Cache<String, CompactedRecord> cache;

    public CaffeineKvStore(KvStoreProperties properties) {
        this.cache = Caffeine.newBuilder()
                .maximumSize(properties.getCaffeine().getMaximumSize())
                .build();
    }

    @Override
    public void put(String key, CompactedRecord record) {
        cache.put(key, record);
    }

    @Override
    public Optional<CompactedRecord> get(String key) {
        return Optional.ofNullable(cache.getIfPresent(key));
    }

    @Override
    public void delete(String key) {
        cache.invalidate(key);
    }

    @Override
    public long size() {
        return cache.estimatedSize();
    }

    @Override
    public Stream<String> keys(String prefix) {
        Stream<String> all = cache.asMap().keySet().stream();
        return prefix == null || prefix.isEmpty() ? all : all.filter(k -> k.startsWith(prefix));
    }
}
