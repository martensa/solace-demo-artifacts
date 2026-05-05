package com.solace.labs.mi.topiccompaction.delete;

import com.solace.labs.mi.topiccompaction.command.CommandEvent;
import com.solace.labs.mi.topiccompaction.kvstore.KvStore;
import com.solace.labs.mi.topiccompaction.metrics.CompactionMetrics;
import com.solace.labs.mi.topiccompaction.replay.SolacePatternMatcher;
import io.micrometer.observation.annotation.Observed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;

import java.util.stream.Stream;

/**
 * Handles {@link com.solace.labs.mi.topiccompaction.command.CommandType
 * #DELETE} command events.
 *
 * <p>Two modes:
 * <ul>
 *   <li><b>Single delete</b> - {@code key} required, tombstones one
 *       record from the KV store.</li>
 *   <li><b>Cascade delete</b> - optional {@code options.cascade}
 *       Solace pattern; the service iterates the KV store and
 *       tombstones every matching record. {@code key} is still
 *       required (it tombstones first, then runs the cascade).</li>
 * </ul>
 *
 * <p>The framework auto-acks the inbound command message; this
 * service is purely synchronous from the interceptor's perspective.
 * Result/summary publishing is the interceptor's concern.
 */
@Service
public class DeleteCommandService {

    private static final Logger log =
            LoggerFactory.getLogger(DeleteCommandService.class);

    private final KvStore kvStore;
    private final CompactionMetrics metrics;

    public DeleteCommandService(
            KvStore kvStore, CompactionMetrics metrics) {
        this.kvStore = kvStore;
        this.metrics = metrics;
    }

    @Observed(name = "delete.execute",
            contextualName = "delete-command",
            lowCardinalityKeyValues = {"workflow", "delete"})
    public DeleteResult execute(CommandEvent event) {
        try (MDC.MDCCloseable ignored = MDC.putCloseable(
                "service", "delete")) {
            return executeInternal(event);
        }
    }

    private DeleteResult executeInternal(CommandEvent event) {
        if (event.key() == null || event.key().isBlank()) {
            return DeleteResult.failed(event.key(),
                    "Command key is required");
        }

        try (MDC.MDCCloseable ignoredKey = MDC.putCloseable(
                "key", event.key())) {

            // Compute the snapshot of "did the explicit key exist?"
            // before we touch anything. This decouples the
            // single-delete report from the cascade ordering.
            boolean singleExisted =
                    kvStore.get(event.key()).isPresent();

            String cascadePattern = event.stringOption(
                    "cascade", null);
            int cascadeMatched = 0;
            int cascadeDeleted = 0;
            boolean singleHandledByCascade = false;

            if (cascadePattern != null && !cascadePattern.isBlank()) {
                SolacePatternMatcher matcher;
                try {
                    matcher = new SolacePatternMatcher(cascadePattern);
                } catch (IllegalArgumentException e) {
                    return DeleteResult.failed(event.key(),
                            "Invalid cascade pattern: " + e.getMessage());
                }
                singleHandledByCascade = matcher.matches(event.key());
                try (Stream<String> keys =
                             kvStore.keys(matcher.prefixForRocksDb())) {
                    for (String k : (Iterable<String>) keys
                            .filter(matcher::matches)::iterator) {
                        cascadeMatched++;
                        try {
                            kvStore.delete(k);
                            cascadeDeleted++;
                        } catch (Exception e) {
                            log.error("Delete cascade failed for "
                                    + "key={}", k, e);
                        }
                    }
                }
                log.info("Delete cascade: pattern={} matched={} "
                        + "deleted={}",
                        cascadePattern, cascadeMatched, cascadeDeleted);
            }

            // If the explicit key wasn't covered by the cascade,
            // delete it now. (If cascade covered it, the cascade
            // loop already removed it.)
            if (singleExisted && !singleHandledByCascade) {
                kvStore.delete(event.key());
            }
            if (singleExisted) {
                log.info("Delete: tombstoned key={}", event.key());
            } else {
                log.info("Delete: no record for key={}", event.key());
            }

            int directDeletes =
                    singleExisted && !singleHandledByCascade ? 1 : 0;
            int totalDeleted = directDeletes + cascadeDeleted;
            for (int i = 0; i < totalDeleted; i++) {
                metrics.recordDelete();
            }

            return new DeleteResult(event.key(),
                    cascadePattern, singleExisted,
                    cascadeMatched, cascadeDeleted, null);
        }
    }

    /**
     * Outcome of a DELETE command execution.
     */
    public record DeleteResult(
            String key,
            String cascadePattern,
            boolean singleDeleted,
            int cascadeMatched,
            int cascadeDeleted,
            String error) {

        public boolean isSuccess() {
            return error == null;
        }

        public static DeleteResult failed(String key, String error) {
            return new DeleteResult(key, null, false, 0, 0, error);
        }
    }
}
