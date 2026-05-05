package com.solace.labs.mi.topiccompaction.kvstore;

import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.rocksdb.Options;
import org.rocksdb.RocksDB;
import org.rocksdb.RocksDBException;
import org.rocksdb.RocksIterator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Optional;
import java.util.Spliterators;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;

/**
 * RocksDB-backed implementation of {@link KvStore}.
 *
 * <p>Persistent across restarts. Single-process, embedded - no external service.
 * Used in production by Kafka Streams as a state store backend.
 */
public class RocksDbKvStore implements KvStore {

    private static final Logger log = LoggerFactory.getLogger(RocksDbKvStore.class);

    static {
        // RocksDB native lib bootstrap; safe to call multiple times.
        RocksDB.loadLibrary();
    }

    private final KvStoreProperties properties;
    private RocksDB db;
    private Options options;

    public RocksDbKvStore(KvStoreProperties properties) {
        this.properties = properties;
    }

    @PostConstruct
    public void open() {
        Path dir = Path.of(properties.getRocksdb().getPath());
        try {
            Files.createDirectories(dir);
        } catch (java.io.IOException e) {
            throw new IllegalStateException("Cannot create RocksDB directory: " + dir, e);
        }
        options = new Options()
                .setCreateIfMissing(true)
                .setMaxOpenFiles(properties.getRocksdb().getMaxOpenFiles());
        try {
            db = RocksDB.open(options, dir.toString());
        } catch (RocksDBException e) {
            options.close();
            throw new KvStoreException("Failed to open RocksDB at " + dir, e);
        }
        log.info("RocksDB KV store opened at {}", dir.toAbsolutePath());
    }

    @PreDestroy
    public void close() {
        if (db != null) {
            try {
                db.syncWal();
            } catch (RocksDBException e) {
                log.warn("Error syncing RocksDB WAL on shutdown", e);
            }
            db.close();
        }
        if (options != null) {
            options.close();
        }
        log.info("RocksDB KV store closed");
    }

    @Override
    public void put(String key, CompactedRecord record) {
        try {
            db.put(key.getBytes(StandardCharsets.UTF_8), RecordCodec.encode(record));
        } catch (RocksDBException e) {
            throw new KvStoreException("RocksDB put failed for key: " + key, e);
        }
    }

    @Override
    public Optional<CompactedRecord> get(String key) {
        try {
            byte[] bytes = db.get(key.getBytes(StandardCharsets.UTF_8));
            return bytes == null ? Optional.empty() : Optional.of(RecordCodec.decode(bytes));
        } catch (RocksDBException e) {
            throw new KvStoreException("RocksDB get failed for key: " + key, e);
        }
    }

    @Override
    public void delete(String key) {
        try {
            db.delete(key.getBytes(StandardCharsets.UTF_8));
        } catch (RocksDBException e) {
            throw new KvStoreException("RocksDB delete failed for key: " + key, e);
        }
    }

    @Override
    public long size() {
        try {
            // estimate-num-keys is approximate but cheap; exact count requires a full scan.
            String value = db.getProperty("rocksdb.estimate-num-keys");
            return value == null ? 0L : Long.parseLong(value);
        } catch (RocksDBException e) {
            log.warn("Failed to read RocksDB estimate-num-keys", e);
            return -1L;
        }
    }

    @Override
    public Stream<String> keys(String prefix) {
        RocksIterator it = db.newIterator();
        if (prefix == null || prefix.isEmpty()) {
            it.seekToFirst();
        } else {
            it.seek(prefix.getBytes(StandardCharsets.UTF_8));
        }
        Spliterators.AbstractSpliterator<String> spliterator =
                new Spliterators.AbstractSpliterator<>(Long.MAX_VALUE, java.util.Spliterator.ORDERED) {
                    @Override
                    public boolean tryAdvance(java.util.function.Consumer<? super String> action) {
                        if (!it.isValid()) {
                            return false;
                        }
                        String key = new String(it.key(), StandardCharsets.UTF_8);
                        if (prefix != null && !prefix.isEmpty() && !key.startsWith(prefix)) {
                            return false;
                        }
                        action.accept(key);
                        it.next();
                        return true;
                    }
                };
        return StreamSupport.stream(spliterator, false).onClose(it::close);
    }
}
