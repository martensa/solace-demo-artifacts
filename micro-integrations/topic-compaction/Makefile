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
        provision-queues smoke clean

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
