# gebit-price-agent-demo UC1 -- see README.md (setup) and RUNBOOK.md (operation).
# Targets of UC1-BUILD-SPEC 12.5. Settings come from .env (scripts/lib.sh); the
# variables below can be overridden on the command line.
# TARGET=aks (environment or command line; AKS-MIGRATION-PLAN 1.4): the scripts read
# .env.aks only and kubectl runs with the AKS kubeconfig and context (scripts/lib.sh).
SHELL := /bin/bash
TARGET := $(if $(TARGET),$(TARGET),lab)
ifneq ($(TARGET),lab)
ifneq ($(TARGET),aks)
$(error TARGET must be lab or aks, not '$(TARGET)')
endif
endif
AKS_FQDN ?= eurocis-showcase.germanywestcentral.cloudapp.azure.com
NS ?= gpos-demo
GPOS_IMAGE ?= registry.solace.lab/gpos-demo/gpos-demo
GPOS_VERSION ?= 0.1.3
IMAGE := $(GPOS_IMAGE):$(GPOS_VERSION)
CONTAINER_CLI ?= docker
PY := .venv/bin/python
ifeq ($(TARGET),aks)
# exported on aks only (a plain lab make passes no TARGET to its recipes, as before)
export TARGET
# kubectl through scripts/lib.sh: .env.aks, AKS kubeconfig and context, lab-URL guard
KUBECTL := bash -c '. scripts/lib.sh && kubectl "$$@"' kubectl
# never .env on aks: the recipes that need it are lab-only
LOAD_ENV = echo "ERROR: make $@ runs against the lab only (unset TARGET)" >&2; exit 1;
# the offline tests are target-neutral: TARGET=aks of the shell never reaches pytest
PYTEST := env -u TARGET $(PY) -m pytest -q
else
KUBECTL := kubectl
# .env (if present) for recipes that need it; GEBIT descriptors are only READ
LOAD_ENV := set -a; if [ -f .env ]; then . ./.env; fi; set +a;
PYTEST := $(PY) -m pytest -q
endif
GEBIT_DIR := $${GEBIT_DESCRIPTOR_DIR:-$$HOME/Downloads/Gebit}
GEBIT_SETS := $(GEBIT_DIR)/purchase-api-2.50.0.pb:$(GEBIT_DIR)/receipt-api-2.13.0.pb
TILL ?= 01
SCENARIO ?= S1
MODE ?= approve
RUNS ?= 1
ANSWER_DELAY ?= 0
CTL := $(KUBECTL) -n $(NS) exec deploy/gpos-ui -- python -m gposdemo.ui.ctl

.PHONY: help venv protos test test-ops test-db test-gebit test-int hygiene build push \
        db-up k8s-up manifests mesh-up demo-up demo-reset demo-watch smoke gate-verify \
        e2e port-forward status logs urls uninstall

help:  ## list the targets
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

venv:  ## .venv with Python 3.13 and app/requirements-dev.txt
	python3.13 -m venv .venv
	$(PY) -m pip install -q -r app/requirements-dev.txt

protos:  ## showcase descriptor set -> build/descriptors/showcase.pb
	PYTHONPATH=app $(PY) -m gposdemo.common.protoc

test:  ## unit tests without Docker (app and scripts)
	$(PYTEST) app/tests -m "not db and not gebit and not integration"
	$(PYTEST) scripts/tests

test-ops:  ## offline tests of scripts/ and mesh/ only
	$(PYTEST) scripts/tests

ifneq ($(TARGET),aks)
test-db:  ## tests with the scratch DB gpos_ut on the host container postgres
	$(PYTEST) app/tests -m "db and not integration"
else
# the scratch DB lives in the lab host container postgres, never on AKS
test-db:
	@echo "ERROR: make $@ runs against the lab only (unset TARGET)" >&2
	@exit 1
endif

test-gebit:  ## tests that need the GEBIT descriptor sets (read from GEBIT_DESCRIPTOR_DIR)
	@$(LOAD_ENV) GEBIT_DESCRIPTOR_SETS="$(GEBIT_SETS)" \
	  $(PYTEST) app/tests -m "gebit and not integration"

test-int:  ## integration without SAM (DB gpos_it + GEBIT descriptors, spec 13.2)
	@$(LOAD_ENV) GEBIT_DESCRIPTOR_SETS="$(GEBIT_SETS)" $(PYTEST) app/tests -m integration

hygiene:  ## no GEBIT material, no LLM key, no key-bearing config (spec 12.6)
	scripts/check_hygiene.sh

ifneq ($(TARGET),aks)
build:  ## build the image (one image, six commands)
	$(CONTAINER_CLI) build -f app/Dockerfile -t $(IMAGE) .

push: build  ## push the image to registry.solace.lab
	$(CONTAINER_CLI) push $(IMAGE)
endif

db-up:  ## DB gpos: roles, schemas, passwords, seed, checks
	scripts/install.sh db

ifneq ($(TARGET),aks)
k8s-up: push  ## image + namespace gpos-demo (Secrets from .env, six Deployments)
	scripts/install.sh k8s

manifests:  ## connector manifests from the image (--dump-tools, spec 8.5)
	$(PY) scripts/gen_connector_manifest.py --from-image $(IMAGE)
endif

mesh-up:  ## SAM: RBAC, connectors, agents, workflows, probe + booth entrypoint (spec 9.8)
	scripts/install.sh mesh

ifneq ($(TARGET),aks)
demo-up: hygiene db-up k8s-up mesh-up smoke urls  ## everything, idempotent
else
# the lab image under the lab tag in registry.solace.lab: an AKS command never builds,
# pushes or runs it (the ACR push is runbook A20); AKS installs via scripts/install.sh
build push k8s-up manifests demo-up:
	@echo "ERROR: make $@ builds, pushes or runs the lab image (registry.solace.lab);" \
	  "TARGET=aks: scripts/install.sh pg|db|k8s|mesh|all, ACR push per runbook A20" >&2
	@exit 1
endif

demo-reset:  ## back to the starting state incl. inbox and queues (spec 11.7)
	scripts/reset.sh

demo-watch:  ## inbox watcher during the fair (duplicate and orphaned requests)
	$(PY) scripts/sam_inbox.py watch

smoke:  ## lab smoke test without SAM, test till 99 (spec 13.3)
	scripts/smoke.sh

gate-verify:  ## gate verification on probe till 98 incl. A9/A10, ~11 min (spec 9.9)
	scripts/e2e.sh --gate-verify

e2e:  ## end to end with SAM: TILL=01|98 SCENARIO=S1..S8 MODE=approve|deny|timeout RUNS=n
	scripts/e2e.sh --till $(TILL) --scenario $(SCENARIO) --mode $(MODE) --runs $(RUNS) \
	  --answer-delay $(ANSWER_DELAY)

port-forward:  ## gRPC 50051-50053, MCP 8765/8766/8771-8773, UI http://localhost:8090
	scripts/port_forward.sh

status:  ## pods and the BFF state
	$(KUBECTL) -n $(NS) get pods -o wide
	$(CTL) state

logs:  ## follow all component logs
	$(KUBECTL) -n $(NS) logs -f -l app.kubernetes.io/part-of=gpos-demo \
	  --all-containers --max-log-requests 8 --prefix

urls:  ## print the demo URLs
ifeq ($(TARGET),aks)
	@echo "Kasse     https://$(AKS_FQDN)/kasse"
	@echo "Monitor   https://$(AKS_FQDN)/monitor"
	@echo "SAM       https://$(AKS_FQDN)/   (approvals: log in as marktleitung)"
	@echo "gRPC      $(AKS_FQDN):443   (grpcurl $(AKS_FQDN):443 list)"
else
	@echo "Kasse     https://gpos.solace.lab/kasse     (fallback: make port-forward,"
	@echo "                                             then http://localhost:8090/kasse)"
	@echo "Monitor   https://gpos.solace.lab/monitor"
	@echo "SAM       https://sam.solace.lab            (approvals: log in as marktleitung)"
	@echo "gRPC      gpos-grpc / gpos-wws-grpc / gpos-loyalty-grpc.solace.lab:443"
endif

uninstall:  ## remove everything the demo created (DB only with scripts/uninstall.sh --drop-db)
	scripts/uninstall.sh
