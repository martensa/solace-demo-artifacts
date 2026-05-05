package com.solace.labs.mi.topiccompaction.security;

import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * Operator-tunable REST security settings. Two roles:
 *
 * <ul>
 *   <li>{@code mi-user} - read-only access to {@code /api/v1/kv}
 *       (lookup, list)</li>
 *   <li>{@code mi-admin} - everything {@code mi-user} can do, plus
 *       {@code DELETE /api/v1/kv/...} and the
 *       {@code /api/v1/admin/*} endpoints (backup/restore)</li>
 * </ul>
 *
 * <p>Disabled by default in the docker-compose dev mode for
 * convenience; the K8s overlay enables it. Public endpoints
 * ({@code /actuator/health/*} and {@code /actuator/prometheus})
 * never require auth.
 *
 * <p>Credentials live in environment variables backed by the
 * {@code .env} file (docker-compose) or a Kubernetes
 * {@code Secret}.
 */
@ConfigurationProperties(prefix = "topic-compaction.security")
@Validated
public class SecurityProperties {

    /** Master switch. */
    private boolean enabled = false;

    /** Read-only user credentials. */
    private User user = new User();

    /** Admin user credentials. */
    private User admin = new User();

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean v) { this.enabled = v; }

    public User getUser() { return user; }
    public void setUser(User v) { this.user = v; }

    public User getAdmin() { return admin; }
    public void setAdmin(User v) { this.admin = v; }

    public static class User {
        @NotBlank(message = "username must not be blank")
        private String name = "mi-user";

        @NotBlank(message = "password must not be blank")
        private String password = "change-me";

        public String getName() { return name; }
        public void setName(String v) { this.name = v; }

        public String getPassword() { return password; }
        public void setPassword(String v) { this.password = v; }
    }
}
