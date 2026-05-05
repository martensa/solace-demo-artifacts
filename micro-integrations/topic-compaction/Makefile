# =============================================================================
# Topic Compaction MI - convenience targets
# Modeled after the SAM `make secrets` pattern: real values live in .env
# (gitignored), placeholders live in .env.example (committed).
# =============================================================================

ENV_FILE := .env
COMPOSE_FILE := deploy/docker-compose/compose.yaml
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE)

# Use the user's docker config so jib can find the Rancher Desktop
# credential helper. Override on the command line if you use a different setup.
DOCKER_CONFIG ?= $(HOME)/.docker

.DEFAULT_GOAL := help

.PHONY: help env-check env-init build test image up down restart logs status \
        provision-queues smoke clean \
        k8s-deploy k8s-status k8s-logs k8s-port-forward k8s-restart \
        k8s-undeploy k8s-undeploy-purge

help:
	@echo "Topic Compaction MI - available targets:"
	@echo ""
	@echo "  Setup:"
	@echo "    env-init           Copy .env.example to .env (run once)"
	@echo "    env-check          Verify .env exists and has required keys"
	@echo "    provision-queues   Run examples/init-queues.sh against your broker"
	@echo ""
	@echo "  Build:"
	@echo "    build              ./mvnw clean package"
	@echo "    test               ./mvnw test"
	@echo "    image              Build container image into local Docker daemon"
	@echo ""
	@echo "  Run:"
	@echo "    up                 Start the MI"
	@echo "    down               Stop the MI (keeps volumes)"
	@echo "    restart            Restart only the MI container"
	@echo "    logs               Tail MI logs"
	@echo "    status             docker compose ps"
	@echo ""
	@echo "  Test:"
	@echo "    smoke              Run the end-to-end smoke test"
	@echo ""
	@echo "  Cleanup:"
	@echo "    clean              Down + remove volumes + remove target/"
	@echo ""
	@echo "  Kubernetes:"
	@echo "    k8s-deploy           Idempotent deploy to mi-solace-lab"
	@echo "    k8s-status           Show pod / svc / pvc / monitoring"
	@echo "    k8s-logs             Tail MI logs"
	@echo "    k8s-port-forward     Forward 18090 -> service:8090"
	@echo "    k8s-restart          Rollout restart the deployment"
	@echo "    k8s-undeploy         Remove workload + monitoring; keep PVC"
	@echo "    k8s-undeploy-purge   Remove everything incl. PVC + namespace"

env-init:
	@if [ -f $(ENV_FILE) ]; then \
		echo "$(ENV_FILE) already exists - leaving it alone"; \
	else \
		cp .env.example $(ENV_FILE); \
		echo "Created $(ENV_FILE) from .env.example."; \
		echo "Edit it to fill in your Solace broker credentials."; \
	fi

env-check:
	@if [ ! -f $(ENV_FILE) ]; then \
		echo "ERROR: $(ENV_FILE) not found."; \
		echo "Run: make env-init && \$$EDITOR $(ENV_FILE)"; \
		exit 1; \
	fi
	@for key in SOLACE_HOST SOLACE_VPN SOLACE_USERNAME SOLACE_PASSWORD; do \
		if ! grep -qE "^$$key=.+" $(ENV_FILE); then \
			echo "ERROR: $$key is missing or empty in $(ENV_FILE)"; \
			exit 1; \
		fi; \
	done
	@echo "$(ENV_FILE) looks OK."

build:
	./mvnw clean package -DskipTests

test:
	./mvnw test

image:
	DOCKER_CONFIG=$(DOCKER_CONFIG) ./mvnw package jib:dockerBuild -DskipTests

up: env-check
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart topic-compaction-mi

logs:
	$(COMPOSE) logs -f topic-compaction-mi

status:
	$(COMPOSE) ps

provision-queues: env-check
	@echo "Set SEMP_URL in $(ENV_FILE) (or pass it inline) before running this."
	./examples/init-queues.sh

smoke: env-check
	./examples/smoke-test.sh

clean:
	$(COMPOSE) down -v
	rm -rf target/

# ---------------------------------------------------------------------------
# Kubernetes deployment targets (V1.0 / Phase 5)
# ---------------------------------------------------------------------------
KUBECTL ?= kubectl
K8S_NAMESPACE ?= mi-solace-lab

k8s-deploy:
	./deploy/k8s/scripts/start.sh

k8s-status:
	@echo "--- Workload ---"
	$(KUBECTL) -n $(K8S_NAMESPACE) get deploy,svc,pvc,pdb,networkpolicy
	@echo
	@echo "--- Pods ---"
	$(KUBECTL) -n $(K8S_NAMESPACE) get pods \
		-l app.kubernetes.io/name=topic-compaction-mi
	@echo
	@echo "--- Monitoring artifacts ---"
	$(KUBECTL) -n monitoring get servicemonitor,prometheusrule \
		-l app.kubernetes.io/name=topic-compaction-mi 2>/dev/null \
		|| echo "(monitoring namespace unreachable)"

k8s-logs:
	$(KUBECTL) -n $(K8S_NAMESPACE) logs -f \
		-l app.kubernetes.io/name=topic-compaction-mi

k8s-port-forward:
	@echo "Port-forwarding 18090 -> service:8090. Ctrl-C to stop."
	$(KUBECTL) -n $(K8S_NAMESPACE) port-forward \
		svc/topic-compaction-mi 18090:8090

k8s-restart:
	$(KUBECTL) -n $(K8S_NAMESPACE) rollout restart \
		deployment/topic-compaction-mi
	$(KUBECTL) -n $(K8S_NAMESPACE) rollout status \
		deployment/topic-compaction-mi --timeout=120s

k8s-undeploy:
	./deploy/k8s/scripts/stop.sh

k8s-undeploy-purge:
	./deploy/k8s/scripts/stop.sh --delete-namespace
