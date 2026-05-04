package com.solace.labs.mi.topiccompaction.kvstore;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * Configuration properties for the KV store.
 *
 * <pre>
 * topic-compaction.kvstore:
 *   backend: rocksdb            # rocksdb | caffeine
 *   rocksdb:
 *     path: ./data/rocksdb
 *     max-open-files: 1000
 *   caffeine:
 *     maximum-size: 1000000
 * </pre>
 */
@ConfigurationProperties(prefix = "topic-compaction.kvstore")
public class KvStoreProperties {

    public enum Backend { rocksdb, caffeine }

    private Backend backend = Backend.rocksdb;
    private RocksDb rocksdb = new RocksDb();
    private Caffeine caffeine = new Caffeine();

    public Backend getBackend() { return backend; }
    public void setBackend(Backend backend) { this.backend = backend; }
    public RocksDb getRocksdb() { return rocksdb; }
    public void setRocksdb(RocksDb rocksdb) { this.rocksdb = rocksdb; }
    public Caffeine getCaffeine() { return caffeine; }
    public void setCaffeine(Caffeine caffeine) { this.caffeine = caffeine; }

    public static class RocksDb {
        private String path = "./data/rocksdb";
        private int maxOpenFiles = 1000;

        public String getPath() { return path; }
        public void setPath(String path) { this.path = path; }
        public int getMaxOpenFiles() { return maxOpenFiles; }
        public void setMaxOpenFiles(int maxOpenFiles) { this.maxOpenFiles = maxOpenFiles; }
    }

    public static class Caffeine {
        private long maximumSize = 1_000_000L;

        public long getMaximumSize() { return maximumSize; }
        public void setMaximumSize(long maximumSize) { this.maximumSize = maximumSize; }
    }
}
