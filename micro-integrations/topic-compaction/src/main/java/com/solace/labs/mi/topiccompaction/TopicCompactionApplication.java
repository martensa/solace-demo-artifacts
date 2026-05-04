package com.solace.labs.mi.topiccompaction;

import com.solace.labs.mi.topiccompaction.compaction.CompactionProperties;
import com.solace.labs.mi.topiccompaction.lookup.LookupProperties;
import com.solace.labs.mi.topiccompaction.replay.ReplayProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

/**
 * Main entry point for the Topic Compaction Micro-Integration.
 *
 * <p>This MI maintains a key-value store of last-seen messages per Solace topic and
 * supports on-demand replay via command events. It is a Solace-native alternative to
 * Kafka log compaction with several advantages:
 * <ul>
 *   <li>Immediate compaction (no eventual cleanup background process)</li>
 *   <li>Direct O(1) lookup via REST and Solace Request/Reply</li>
 *   <li>On-demand replay triggered by command events</li>
 *   <li>Hierarchical topic support via Solace wildcard subscriptions</li>
 * </ul>
 *
 * <p>Note: the MI SDK 3.0.6 auto-configures
 * {@code RequiresTransformEnabledConfigurationValidation} via
 * {@code ConfigurationValidationAutoConfiguration}, so we do not need to
 * declare it as an explicit bean here (the PDF guide is out of date for 3.0.6;
 * declaring it explicitly causes a {@code BeanDefinitionOverrideException}).
 */
@SpringBootApplication
@EnableConfigurationProperties({CompactionProperties.class, ReplayProperties.class, LookupProperties.class})
public class TopicCompactionApplication {

    public static void main(String[] args) {
        SpringApplication.run(TopicCompactionApplication.class, args);
    }
}
