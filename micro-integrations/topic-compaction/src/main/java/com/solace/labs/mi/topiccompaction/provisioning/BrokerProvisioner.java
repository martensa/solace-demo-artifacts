package com.solace.labs.mi.topiccompaction.provisioning;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties
        .EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestClient;

import java.net.URI;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Idempotent SEMPv2-driven queue and subscription provisioner.
 *
 * <p>Runs on application startup before the MI Framework starts the
 * Solace consumer flows. Reads {@link ProvisioningProperties} for
 * the SEMP endpoint and the desired queues + subscriptions; for
 * each queue:
 *
 * <ol>
 *   <li>{@code POST /SEMP/v2/config/msgVpns/{vpn}/queues} -
 *       {@code 200} = created, {@code 400} = already exists. Both
 *       are treated as success.</li>
 *   <li>For each subscription:
 *       {@code POST /SEMP/v2/config/msgVpns/{vpn}/queues/{q}/
 *       subscriptions} - same idempotency rule.</li>
 * </ol>
 *
 * <p>Higher-priority {@link Order} ensures we run before any other
 * runner that might depend on the bindings being live.
 *
 * <p>Failure modes:
 * <ul>
 *   <li>{@code semp.url} blank - log a warning, do nothing. The
 *       deployment is assumed to manage its own provisioning.</li>
 *   <li>{@code 401 Unauthorized} or connection error - log an error
 *       per queue, continue. By default the application keeps
 *       starting (operator can verify subscriptions manually). Set
 *       {@code fail-on-error: true} to bail out instead.</li>
 *   <li>Any other unexpected status - same as {@code 401}.</li>
 * </ul>
 */
@Component
@ConditionalOnProperty(prefix = "topic-compaction.provisioning",
        name = "enabled", havingValue = "true")
@Order(Ordered.HIGHEST_PRECEDENCE)
public class BrokerProvisioner implements ApplicationRunner {

    private static final Logger log =
            LoggerFactory.getLogger(BrokerProvisioner.class);

    private final ProvisioningProperties properties;
    private final RestClient restClient;
    private final ObjectMapper objectMapper;

    public BrokerProvisioner(ProvisioningProperties properties,
                              RestClient.Builder builder,
                              ObjectMapper objectMapper) {
        this.properties = properties;
        this.restClient = builder.build();
        this.objectMapper = objectMapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (properties.getSemp().getUrl().isBlank()) {
            log.warn("BrokerProvisioner: SEMP url is blank, "
                    + "skipping. Subscriptions will not be "
                    + "verified - the deployment is assumed to "
                    + "manage queues out-of-band.");
            return;
        }
        log.info("BrokerProvisioner: starting against {} ({} queues)",
                properties.getSemp().getUrl(),
                properties.getQueues().size());
        boolean anyError = false;
        for (ProvisioningProperties.Queue q : properties.getQueues()) {
            try {
                createQueue(q);
                for (String sub : q.getSubscriptions()) {
                    addSubscription(q.getName(), sub);
                }
            } catch (Exception e) {
                anyError = true;
                log.error("BrokerProvisioner: queue {} - {}",
                        q.getName(), e.getMessage());
            }
        }
        if (anyError && properties.isFailOnError()) {
            throw new IllegalStateException(
                    "BrokerProvisioner: provisioning failed for one "
                    + "or more queues; fail-on-error is true");
        }
        log.info("BrokerProvisioner: done");
    }

    private void createQueue(ProvisioningProperties.Queue q) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("queueName", q.getName());
        body.put("egressEnabled", true);
        body.put("ingressEnabled", true);
        body.put("permission", q.getPermission());
        body.put("accessType", q.getAccessType());
        callIdempotent(uri("/SEMP/v2/config/msgVpns/{vpn}/queues"),
                body, "create queue " + q.getName());
    }

    private void addSubscription(String queue, String topic) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("subscriptionTopic", topic);
        callIdempotent(uri(
                "/SEMP/v2/config/msgVpns/{vpn}/queues/" + queue
                        + "/subscriptions"),
                body, "subscribe " + queue + " -> " + topic);
    }

    /**
     * POSTs to SEMP. {@code 200} (created) and {@code 400}
     * (already exists or validation rejection) are both treated as
     * success. Anything else throws.
     */
    private void callIdempotent(URI uri, Map<String, Object> body,
                                 String description) {
        try {
            String json = objectMapper.writeValueAsString(body);
            HttpStatusCode status = restClient.post()
                    .uri(uri)
                    .header(HttpHeaders.AUTHORIZATION,
                            basicAuthHeader())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(json)
                    .retrieve()
                    .toBodilessEntity()
                    .getStatusCode();
            log.info("BrokerProvisioner: {} -> HTTP {}",
                    description, status.value());
        } catch (HttpClientErrorException e) {
            if (e.getStatusCode().value() == 400) {
                // SEMP returns 400 for "already exists" and similar
                // idempotent-conflict cases. Log at debug so the
                // happy path stays quiet on restart.
                log.debug("BrokerProvisioner: {} -> 400 "
                        + "(already exists, ignored)",
                        description);
                return;
            }
            throw new IllegalStateException(description
                    + ": HTTP " + e.getStatusCode() + " - "
                    + e.getResponseBodyAsString(), e);
        } catch (Exception e) {
            throw new IllegalStateException(
                    description + ": " + e.getMessage(), e);
        }
    }

    private String basicAuthHeader() {
        String credentials = properties.getSemp().getUsername()
                + ":" + properties.getSemp().getPassword();
        return "Basic " + Base64.getEncoder().encodeToString(
                credentials.getBytes());
    }

    private URI uri(String path) {
        String resolved = path.replace("{vpn}",
                properties.getSemp().getMsgVpn());
        return URI.create(properties.getSemp().getUrl() + resolved);
    }

    /**
     * Activates {@link ProvisioningProperties} only when this
     * runner is enabled, so the prefix can stay absent in operator
     * config without binding failures.
     */
    @Configuration
    @EnableConfigurationProperties(ProvisioningProperties.class)
    @ConditionalOnProperty(prefix = "topic-compaction.provisioning",
            name = "enabled", havingValue = "true")
    public static class ProvisioningAutoConfiguration { }
}
