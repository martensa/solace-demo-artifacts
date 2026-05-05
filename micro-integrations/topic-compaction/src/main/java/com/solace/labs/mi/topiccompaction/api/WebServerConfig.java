package com.solace.labs.mi.topiccompaction.api;

import org.springframework.boot.web.embedded.tomcat.TomcatServletWebServerFactory;
import org.springframework.boot.web.server.WebServerFactoryCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Tomcat connector tuning that the REST surface of the MI relies on.
 *
 * <p>The KV store keys are full Solace topics with embedded slashes.
 * The controller's {@code @GetMapping("/{*key}")} accepts unencoded
 * slashes natively, but legacy clients still URL-encode their
 * slashes as {@code %2F}. By default Tomcat rejects encoded-slash
 * paths with {@code 400 Bad Request} as a path-traversal hardening,
 * before the request even reaches Spring's dispatcher.
 *
 * <p>We switch the connector to {@code PASS_THROUGH} encoded-solidus
 * handling so that {@code %2F} survives down to the controller, where
 * {@code KvStoreController#normalizeKey} URL-decodes it. This keeps
 * both encoded and unencoded slashes working without changing the
 * controller's already-tested decoding logic.
 *
 * <p>Reference: Tomcat 10
 * {@code Connector#setEncodedSolidusHandling(String)}.
 */
@Configuration
public class WebServerConfig {

    @Bean
    public WebServerFactoryCustomizer<TomcatServletWebServerFactory>
            tomcatEncodedSlashCustomizer() {
        return factory -> factory.addConnectorCustomizers(
                connector -> connector.setEncodedSolidusHandling(
                        "passthrough"));
    }
}
