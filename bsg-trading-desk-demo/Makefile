# BSG trading desk demo -- see README.md (setup) and RUNBOOK.md (show).
SHELL := /bin/bash
NS := bsg-demo
VERSION := 0.1.0
IMAGE := registry.solace.lab/bsg-demo/bsg-demo:$(VERSION)
# Rancher Desktop: docker (moby) or nerdctl (containerd)
CONTAINER_CLI ?= docker
PYTHON ?= python3
CTL := kubectl -n $(NS) exec deploy/demo-ui -- python -m bsgdemo.ctl

.PHONY: help test build push k8s-up mesh-up demo-up demo-reset uninstall \
        scenario-wide-spread scenario-market-wide scenario-stale scenario-reset \
        smoke port-forward status logs urls

help:  ## list targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-22s %s\n", $$1, $$2}'

test:  ## unit tests (no broker needed)
	cd app && PYTHONPATH=. $(PYTHON) -m pytest -q tests

build:  ## build the image (one image, four components)
	$(CONTAINER_CLI) build -t $(IMAGE) app

push: build  ## push the image to registry.solace.lab
	$(CONTAINER_CLI) push $(IMAGE)

k8s-up: push  ## publisher, watcher, bsg-tools, demo-ui in namespace bsg-demo
	./scripts/install.sh k8s

mesh-up:  ## SAM connector, agents, workflow, entrypoint (needs Gate 0)
	./scripts/install.sh mesh

demo-up: k8s-up mesh-up urls  ## everything, idempotent

demo-reset:  ## back to the starting state (scenario, watches, status, UI)
	./scripts/reset.sh

uninstall:  ## remove everything the demo created
	./scripts/uninstall.sh

scenario-wide-spread:  ## ISSUER=alpha DURATION=30
	$(CTL) scenario wide_spread --issuer $(or $(ISSUER),alpha) --duration $(or $(DURATION),30)

scenario-market-wide:  ## DURATION=30 (reference jump, all issuers widen, news)
	$(CTL) scenario market_wide --duration $(or $(DURATION),30)

scenario-stale:  ## ISSUER=beta DURATION=20 (issuer stops quoting)
	$(CTL) scenario stale --issuer $(or $(ISSUER),beta) --duration $(or $(DURATION),20)

scenario-reset:  ## end the active scenario, reference levels back
	$(CTL) scenario reset

smoke:  ## deterministic path without SAM (needs make port-forward in another shell)
	$(PYTHON) scripts/smoke_tools.py --mcp http://127.0.0.1:8765/mcp \
	  --watcher http://127.0.0.1:8080 --mqtt-host $${MQTT_HOST:-127.0.0.1} \
	  --mqtt-port $${MQTT_PORT:-1883} --mqtt-user $${MQTT_USERNAME:-default} \
	  --mqtt-pass $${MQTT_PASSWORD:-}

port-forward:  ## UI :8090, watcher :8080, bsg-tools :8765 on localhost
	kubectl -n $(NS) port-forward svc/demo-ui 8090:80 & \
	kubectl -n $(NS) port-forward svc/feed-watcher 8080:8080 & \
	kubectl -n $(NS) port-forward svc/bsg-tools 8765:8765 & wait

status:  ## pods and watcher health
	kubectl -n $(NS) get pods -o wide
	kubectl -n $(NS) exec deploy/demo-ui -- python -c \
	  "import httpx; print(httpx.get('http://feed-watcher.bsg-demo.svc:8080/health').json())"

logs:  ## follow all component logs
	kubectl -n $(NS) logs -f -l app.kubernetes.io/part-of=bsg-trading-desk-demo \
	  --all-containers --max-log-requests 8 --prefix

urls:  ## print the demo URLs
	@echo "Demo UI   https://bsg-desk.solace.lab   (fallback: make port-forward -> http://localhost:8090)"
	@echo "SAM       https://sam.solace.lab        (log in as power_user)"
	@echo "Grafana   https://monitoring.solace.lab"
