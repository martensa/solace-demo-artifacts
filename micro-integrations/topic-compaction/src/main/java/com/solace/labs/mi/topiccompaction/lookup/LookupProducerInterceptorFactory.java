package com.solace.labs.mi.topiccompaction.lookup;

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

import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;

/**
 * Producer interceptor for the lookup workflow.
 *
 * <p>For each lookup request flowing through the workflow:
 * <ol>
 *   <li>Resolves the key via {@link LookupService#resolve}.</li>
 *   <li>Replaces the producer message's payload with the looked-up record (or a
 *       not-found document).</li>
 *   <li>Sets the destination to the original request's {@code solace_replyTo}.
 *       This implements Solace Request/Reply semantics through the MI's
 *       workflow model.</li>
 * </ol>
 */
@Component
public class LookupProducerInterceptorFactory implements ProducerBindingMessageInterceptorFactory {

    private static final Logger log = LoggerFactory.getLogger(LookupProducerInterceptorFactory.class);
    private static final String SOLACE_DESTINATION_HEADER = "solace_destination";
    private static final String SOLACE_REPLY_TO_HEADER = "solace_replyTo";

    private final LookupService service;
    private final Set<String> outputBindingNames;

    public LookupProducerInterceptorFactory(LookupService service, LookupProperties properties) {
        this.service = service;
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
        log.info("Attaching LookupInterceptor to Solace producer binding: {}", bindingName);
        return new Interceptor();
    }

    @Override
    public int getOrder() {
        return 0;
    }

    private final class Interceptor implements ProducerBindingMessageInterceptor {
        @Override
        public Message<?> before(Message<?> message) {
            LookupService.Result result = service.resolve(message);

            // Reply destination: take from request's solace_replyTo. If absent we
            // fall back to a fixed not-found topic - clients without reply-to
            // headers won't see the response, but the MI stays alive.
            Object replyTo = message.getHeaders().get(SOLACE_REPLY_TO_HEADER);
            String destination = replyTo == null
                    ? "topic-compaction/lookup/no-reply-to"
                    : replyTo.toString();

            Map<String, Object> headers = new LinkedHashMap<>(result.headers());
            headers.put(SOLACE_DESTINATION_HEADER, destination);
            headers.put(BinderHeaders.TARGET_DESTINATION, destination);

            // Echo the correlation id if present so request/reply correlation
            // works on the client side.
            Object correlationId = message.getHeaders().get("solace_correlationId");
            if (correlationId != null) {
                headers.put("solace_correlationId", correlationId);
            }

            return new GenericMessage<>(result.payload(), headers);
        }
    }
}
