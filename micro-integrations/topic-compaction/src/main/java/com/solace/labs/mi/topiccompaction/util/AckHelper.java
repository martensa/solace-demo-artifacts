package com.solace.labs.mi.topiccompaction.util;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.integration.IntegrationMessageHeaderAccessor;
import org.springframework.integration.acks.AcknowledgmentCallback;
import org.springframework.messaging.Message;

/**
 * V1.1.2: utility for manually flushing the consumer-ack on an
 * inbound message before the Spring Integration channel send is
 * suppressed.
 *
 * <p>The MI Framework wraps the consumer interceptor as a Spring
 * Integration {@code ChannelInterceptor#preSend}. Returning
 * {@code null} from {@code preSend} cancels the channel send -
 * but it does NOT acknowledge the inbound message. The
 * {@code JCSMPInboundChannelAdapter} treats the cancelled send as
 * a delivery failure and the broker redelivers up to
 * {@code maxRedeliveryCount=5} before dropping the message. We
 * observed this in V1.1.1 lab testing: a single inbound publish
 * generated 6 audit events (1 + 5 redeliveries), and the queue's
 * {@code maxRedeliveryExceededDiscardedMsgCount} ticked up by 1
 * per inbound message.
 *
 * <p>The fix is to manually flush the
 * {@link AcknowledgmentCallback} that the Solace binder attaches
 * to every inbound message header. Calling
 * {@code acknowledge(ACCEPT)} positively acks the message at the
 * broker, after which returning {@code null} from {@code preSend}
 * is safe - the cancelled send is no longer the broker's signal,
 * the explicit ack is.
 *
 * <p>Defensive: idempotent against missing headers (no-op if the
 * inbound has no callback, e.g. in tests using mock messages) and
 * already-acked state ({@code isAcknowledged()} guard).
 */
public final class AckHelper {

    private static final Logger log = LoggerFactory.getLogger(AckHelper.class);

    private AckHelper() { /* static utility */ }

    /**
     * Flush the inbound ACK with status {@code ACCEPT}. No-op if
     * the message has no callback header or the callback is
     * already in a final state.
     */
    public static void accept(Message<?> message) {
        AcknowledgmentCallback ack = message.getHeaders().get(
                IntegrationMessageHeaderAccessor.ACKNOWLEDGMENT_CALLBACK,
                AcknowledgmentCallback.class);
        if (ack == null) {
            return;
        }
        if (ack.isAcknowledged()) {
            return;
        }
        try {
            ack.acknowledge(AcknowledgmentCallback.Status.ACCEPT);
        } catch (RuntimeException e) {
            log.warn("AckHelper: ACCEPT failed for message: {}", e.getMessage());
        }
    }
}
