package com.solace.labs.mi.topiccompaction.api;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.web.firewall.HttpFirewall;
import org.springframework.security.web.firewall.StrictHttpFirewall;

/**
 * Customizes Spring Security's {@link StrictHttpFirewall} so that
 * URL-encoded slashes ({@code %2F}) reach the controller.
 *
 * <p>Spring Security defaults to rejecting requests whose URL path
 * contains {@code %2F} or {@code %5C} as a path-traversal hardening.
 * The Topic Compaction MI takes Solace topic names as path variables;
 * legacy clients commonly URL-encode embedded slashes. The
 * controller's {@code KvStoreController#normalizeKey} URL-decodes the
 * captured path so both forms (encoded and unencoded) resolve to the
 * same key. To make that work end-to-end the firewall must let the
 * encoded form through.
 *
 * <p>Pairs with {@link WebServerConfig} which relaxes the same
 * restriction at the Tomcat connector level (Tomcat checks happen
 * before Spring Security).
 *
 * <p>This relaxation is safe in V1 because the controller never
 * uses the captured key as a filesystem path or shell argument - it
 * is only used as a RocksDB key and a Solace topic name, neither of
 * which is vulnerable to path-traversal attacks.
 */
@Configuration
public class HttpFirewallConfig {

    @Bean
    public HttpFirewall allowUrlEncodedSlashHttpFirewall() {
        StrictHttpFirewall firewall = new StrictHttpFirewall();
        firewall.setAllowUrlEncodedSlash(true);
        firewall.setAllowUrlEncodedPercent(true);
        return firewall;
    }
}
