package com.solace.labs.mi.topiccompaction.security;

import org.springframework.boot.actuate.autoconfigure.security.servlet
        .EndpointRequest;
import org.springframework.boot.context.properties
        .EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders
        .HttpSecurity;
import org.springframework.security.config.annotation.web.configuration
        .EnableWebSecurity;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning
        .InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Spring Security configuration for the Topic Compaction MI REST
 * surface.
 *
 * <p>Always-on rules (enforced even when authentication itself is
 * disabled):
 * <ul>
 *   <li>{@code /actuator/health} (incl. {@code /liveness} and
 *       {@code /readiness}) - public, for K8s probes</li>
 *   <li>{@code /actuator/prometheus} - public, for the Prometheus
 *       scraper. Restrict via NetworkPolicy in K8s.</li>
 * </ul>
 *
 * <p>When {@code topic-compaction.security.enabled = true}:
 * <ul>
 *   <li>{@code GET /api/v1/kv/...} requires role {@code USER} or
 *       {@code ADMIN}</li>
 *   <li>{@code DELETE /api/v1/kv/...} requires role {@code ADMIN}
 *       (Phase 3 admin operation)</li>
 *   <li>{@code /api/v1/admin/...} requires role {@code ADMIN}</li>
 *   <li>Other actuator endpoints require role {@code ADMIN}</li>
 * </ul>
 *
 * <p>CSRF is disabled because every authenticated REST call is
 * stateless (no browser-form scenario). Frame options remain at
 * default (DENY) - the MI does not host any UI.
 *
 * <p>The configuration pairs with
 * {@code api.HttpFirewallConfig}, which relaxes
 * {@code StrictHttpFirewall} to allow URL-encoded slashes. That
 * relaxation is independent of authentication.
 */
@Configuration
@EnableWebSecurity
@EnableConfigurationProperties(SecurityProperties.class)
public class WebSecurityConfig {

    /** Spring Security role name for read-only KV access. */
    public static final String ROLE_USER = "USER";
    /** Spring Security role name for full admin access. */
    public static final String ROLE_ADMIN = "ADMIN";

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    /**
     * In-memory user store. We accept clear-text passwords from the
     * config (which are environment-injected) and hash them in
     * memory. In production deployments where credentials rotate
     * frequently this should be swapped for a directory-backed
     * provider.
     */
    @Bean
    public InMemoryUserDetailsManager userDetailsService(
            SecurityProperties properties,
            PasswordEncoder passwordEncoder) {
        UserDetails user = User.withUsername(
                        properties.getUser().getName())
                .password(passwordEncoder.encode(
                        properties.getUser().getPassword()))
                .roles(ROLE_USER)
                .build();
        UserDetails admin = User.withUsername(
                        properties.getAdmin().getName())
                .password(passwordEncoder.encode(
                        properties.getAdmin().getPassword()))
                .roles(ROLE_USER, ROLE_ADMIN)
                .build();
        return new InMemoryUserDetailsManager(user, admin);
    }

    @Bean
    public SecurityFilterChain securityFilterChain(
            HttpSecurity http,
            SecurityProperties properties) throws Exception {

        http.csrf(csrf -> csrf.disable())
                .sessionManagement(s -> s.sessionCreationPolicy(
                        org.springframework.security.config.http
                                .SessionCreationPolicy.STATELESS));

        if (!properties.isEnabled()) {
            // Auth disabled: still enforce the firewall rules from
            // HttpFirewallConfig (encoded slashes etc.) but accept
            // every request unauthenticated.
            http.authorizeHttpRequests(authz -> authz
                    .anyRequest().permitAll());
            return http.build();
        }

        http.authorizeHttpRequests(authz -> authz
                // Public probes and metrics
                .requestMatchers(EndpointRequest.to(
                        "health", "prometheus")).permitAll()
                // KV read endpoints - USER or ADMIN
                .requestMatchers(HttpMethod.GET,
                        "/api/v1/kv/**", "/api/v1/kv")
                        .hasAnyRole(ROLE_USER, ROLE_ADMIN)
                // KV delete - ADMIN only (data-destructive)
                .requestMatchers(HttpMethod.DELETE,
                        "/api/v1/kv/**").hasRole(ROLE_ADMIN)
                // Admin endpoints - ADMIN only
                .requestMatchers("/api/v1/admin/**")
                        .hasRole(ROLE_ADMIN)
                // Other actuator endpoints - ADMIN only
                .requestMatchers(EndpointRequest.toAnyEndpoint())
                        .hasRole(ROLE_ADMIN)
                // Anything else - require auth (keeps surprises out)
                .anyRequest().authenticated());

        http.httpBasic(basic -> {});

        return http.build();
    }
}
