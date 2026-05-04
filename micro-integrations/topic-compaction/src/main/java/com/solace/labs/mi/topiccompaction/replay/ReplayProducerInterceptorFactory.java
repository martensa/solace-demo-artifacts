package com.solace.labs.mi.topiccompaction.replay;

import com.solace.connector.core.customizer.ProducerBindingMessageInterceptor;
import com.solace.connector.core.customizer.ProducerBindingMessageInterceptorFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.cloud.stream.binder.BinderHeaders;
import org.springframework.cloud.stream.binder.ProducerProperties;
import org.springframework.lang.Nullable;
import org.springframework.messaging.Message;
import org.springframework.messaging.support.GenericMessage;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Translates the replay workflow's pass-through message (originally a command
 * JSON) into the actual replay event:
 * <ul>
 *   <li>Destination: {@code <commandKey><target-suffix>}</li>
 *   <li>Payload: original message payload from the KV store</li>
 *   <li>Headers: original headers + loop-protection flag</li>
 * </ul>
 *
 * <p>If the lookup fails (unknown key, malformed command), the interceptor
 * publishes a small JSON failure document to a fixed error topic. Operators can
 * subscribe to it for monitoring.
 */
@Component
public class ReplayProducerInterceptorFactory implements ProducerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(ReplayProducerInterceptorFactory.class);
    private static final String SOLACE_DESTINATION_HEADER = "solace_destination";
    private static final String FAILURE_DESTINATION = "topic-compaction/replay/failed";

    private final ReplayService service;
    private final ReplayProperties properties;
    private final Set<String> outputBindingNames;

    public ReplayProducerInterceptorFactory(ReplayService service, ReplayProperties properties) {
        this.service = service;
        this.properties = properties;
        // Symmetric mapping: input-N -> output-N
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
        log.info("Attaching ReplayInterceptor to Solace producer binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor implements ProducerBindingMessageInterceptor {
        @Override
        public Message<?> before(Message<?> message) {
            byte[] commandBytes = bytesFrom(message);
            ReplayService.Decision decision = service.process(commandBytes);

            if (!decision.success()) {
                log.warn("Replay command failed: {}", decision.failure());
                Map<String, Object> errHeaders = new LinkedHashMap<>();
                errHeaders.put(SOLACE_DESTINATION_HEADER, FAILURE_DESTINATION);
                errHeaders.put(BinderHeaders.TARGET_DESTINATION, FAILURE_DESTINATION);
                errHeaders.put("content-type", "application/json");
                return new GenericMessage<>(service.renderFailureDocument(decision.failure()), errHeaders);
            }

            Map<String, Object> headers = new LinkedHashMap<>(decision.headers());
            // Ensure both destination header conventions are set; different Solace
            // binder versions read different headers.
            headers.putIfAbsent(BinderHeaders.TARGET_DESTINATION, decision.destination());
            return new GenericMessage<>(decision.payload(), headers);
        }
    }

    private static byte[] bytesFrom(Message<?> message) {
        Object payload = message.getPayload();
        if (payload instanceof byte[] b) return b;
        if (payload instanceof String s) return s.getBytes(StandardCharsets.UTF_8);
        return String.valueOf(payload).getBytes(StandardCharsets.UTF_8);
    }
}
