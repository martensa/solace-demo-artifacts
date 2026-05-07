package com.solace.labs.mi.topiccompaction.lookup;

import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptorFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.stereotype.Component;

import java.util.HashSet;
import java.util.Set;

/**
 * V1.1.4: pure suppressor on the lookup output binding.
 *
 * <p>Earlier versions of this class performed the lookup
 * synchronously and built the reply message for the binder to
 * publish PERSISTENT on the requestor's {@code solace_replyTo}.
 * That coupled the inbound consumer-ack on the request to the
 * publish-ack on the reply, and Solace REST's
 * {@code /REQUESTS/...} endpoint listens DIRECT on a temp reply
 * queue - PERSISTENT publishes to a DIRECT-only subscriber are
 * silently discarded by the broker
 * ({@code msgSpoolRxDiscardedMsgCount} ticks, no NACK), the
 * publish-ack callback never fires, and the lookup request hangs
 * for the framework's {@code publish-timeout} window before the
 * broker redelivers up to {@code maxRedeliveryCount=5}. Lab
 * measurement: 100% of REST lookup requests timed out at the
 * {@code 504} layer, with {@code ackedMsgCount=0} on the lookup
 * flow.
 *
 * <p>V1.1.4 moves the lookup work to {@code
 * LookupConsumerInterceptorFactory} on the consumer side and
 * publishes the reply via the separate-session
 * {@code DirectAuditPublisher.publishDirectBytes} (DIRECT
 * delivery, matches the requestor's DIRECT subscription). The
 * binder's output-2 path is now suppressed: this class returns
 * {@code null} from {@code before()} so the binder skips the
 * publish, the consumer-ack on the inbound request is flushed
 * via {@link com.solace.labs.mi.topiccompaction.util.AckHelper}
 * by the consumer interceptor, and the reply arrives at the
 * requestor in milliseconds.
 *
 * <p>The class is kept (rather than removed) for the same reasons
 * documented on the other suppressors in this codebase: the
 * workflow definition still wires {@code input-2 -> output-2}, and
 * a {@code null} return suppresses the publish cleanly without
 * the framework attempting a placeholder publish.
 */
@Component
public class LookupProducerInterceptorFactory implements ProducerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(LookupProducerInterceptorFactory.class);

    private final Set<String> outputBindingNames;

    public LookupProducerInterceptorFactory(LookupProperties properties) {
        this.outputBindingNames = new HashSet<>();
        for (String input : properties.getBindingNames()) {
            if (input.startsWith("input-")) {
                outputBindingNames.add("output-" + input.substring("input-".length()));
            }
        }
    }

    @Override
    @Nullable
    public ProducerBindingMessageInterceptor createIfNecessary(String binderType, ProducerProperties producerProperties) {
        if (!"solace".equals(binderType)) {
            return null;
        }
        String bindingName = producerProperties.getBindingName();
        if (!outputBindingNames.contains(bindingName)) {
            return null;
        }
        log.info("Attaching LookupPublishSuppressor to Solace producer binding: {} "
                + "(reply emission moved to LookupConsumerInterceptor in V1.1.4)",
                bindingName);
        return new Suppressor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Suppressor implements ProducerBindingMessageInterceptor {
        @Override
        public Message<?> before(Message<?> message) {
            return null;
        }
    }
}
