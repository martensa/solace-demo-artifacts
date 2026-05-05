package com.solace.labs.mi.topiccompaction.provisioning;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

/**
 * Operator-tunable settings for SEMP-driven queue provisioning.
 *
 * <p>Disabled by default. When enabled, an {@code ApplicationRunner}
 * uses Solace SEMPv2 to idempotently create the configured queues
 * and topic subscriptions before the workflows start consuming.
 *
 * <pre>
 * topic-compaction:
 *   provisioning:
 *     enabled: true
 *     semp:
 *       url: https://mr-connection-...:943
 *       username: mission-control-manager
 *       password: ...
 *       msg-vpn: my-vpn
 *     queues:
 *       - name: compaction.data
 *         subscriptions: [orders/&gt;]
 *         access-type: non-exclusive
 *       - name: compaction.commands
 *         subscriptions: [compacted/command/&gt;]
 *       - name: compaction.lookup
 *         subscriptions: [compacted/lookup/&gt;]
 * </pre>
 *
 * <p>The provisioner treats {@code 400 Bad Request} from SEMP as
 * "already exists" and continues. It fails the application start
 * only on credential / connectivity errors, never on idempotent
 * conflicts.
 */
@ConfigurationProperties(prefix = "topic-compaction.provisioning")
public class ProvisioningProperties {

    /** Master switch. */
    private boolean enabled = false;

    /** When true, the application fails to start on a SEMP error. */
    private boolean failOnError = false;

    /** SEMP coordinates. */
    private Semp semp = new Semp();

    /** Queue + subscription specifications. */
    private List<Queue> queues = new ArrayList<>();

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean v) { this.enabled = v; }

    public boolean isFailOnError() { return failOnError; }
    public void setFailOnError(boolean v) { this.failOnError = v; }

    public Semp getSemp() { return semp; }
    public void setSemp(Semp v) { this.semp = v; }

    public List<Queue> getQueues() { return queues; }
    public void setQueues(List<Queue> v) { this.queues = v; }

    public static class Semp {
        private String url = "";
        private String username = "";
        private String password = "";
        private String msgVpn = "default";

        public String getUrl() { return url; }
        public void setUrl(String v) { this.url = v; }

        public String getUsername() { return username; }
        public void setUsername(String v) { this.username = v; }

        public String getPassword() { return password; }
        public void setPassword(String v) { this.password = v; }

        public String getMsgVpn() { return msgVpn; }
        public void setMsgVpn(String v) { this.msgVpn = v; }
    }

    public static class Queue {
        private String name = "";
        private List<String> subscriptions = new ArrayList<>();
        private String accessType = "non-exclusive";
        private String permission = "consume";

        public String getName() { return name; }
        public void setName(String v) { this.name = v; }

        public List<String> getSubscriptions() { return subscriptions; }
        public void setSubscriptions(List<String> v) { this.subscriptions = v; }

        public String getAccessType() { return accessType; }
        public void setAccessType(String v) { this.accessType = v; }

        public String getPermission() { return permission; }
        public void setPermission(String v) { this.permission = v; }
    }
}
