package com.solace.labs.mi.topiccompaction.kvstore;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Wires the appropriate {@link KvStore} backend based on
 * {@code topic-compaction.kvstore.backend}.
 *
 * <p>Both backends manage their own lifecycle via {@code @PostConstruct} /
 * {@code @PreDestroy} — Spring will invoke those automatically.
 */
@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(KvStoreProperties.class)
public class KvStoreConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "topic-compaction.kvstore", name = "backend", havingValue = "rocksdb", matchIfMissing = true)
    public KvStore rocksDbKvStore(KvStoreProperties properties) {
        return new RocksDbKvStore(properties);
    }

    @Bean
    @ConditionalOnProperty(prefix = "topic-compaction.kvstore", name = "backend", havingValue = "caffeine")
    public KvStore caffeineKvStore(KvStoreProperties properties) {
        return new CaffeineKvStore(properties);
    }
}
