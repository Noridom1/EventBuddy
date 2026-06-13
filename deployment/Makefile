# EventBuddy — dev & deploy targets.
# Lives in deployment/ but operates on the repo ROOT (computed below), so it
# works whether invoked as `make -C deployment <t>` or via the root forwarder.
# Deploy targets wrap the bundled GreenNode AgentBase skill scripts
# ($(ROOT)/.claude/skills/agentbase/scripts) which handle IAM auth + the API.

SHELL := /bin/bash

# Repo root = parent of the directory holding this Makefile (resolved absolutely).
ROOT := $(abspath $(dir $(abspath $(lastword $(MAKEFILE_LIST))))..)

VENV := $(ROOT)/venv
PY   := $(VENV)/bin/python

# Deploy config — override on the command line, e.g. `make deploy FLAVOR=2x4-general`
export RUNTIME_NAME ?= EventBuddy
export FLAVOR       ?= runtime-s2-general-2x4
export ENV_FILE     ?= .env
export PLATFORM     ?= linux/amd64

SCRIPTS := $(ROOT)/.claude/skills/agentbase/scripts

# `make creds` stores IAM creds in .greennode.json, but the bundled skill scripts read
# GREENNODE_CLIENT_ID/SECRET from the environment. Bridge the two so every target that
# calls the API (deploy, destroy, status, endpoint, logs) is authenticated. An already
# exported value wins (?=); otherwise pull it from .greennode.json.
GN_JSON := $(ROOT)/.greennode.json
export GREENNODE_CLIENT_ID     ?= $(shell jq -r '.client_id // .clientId // .iam.client_id // empty' $(GN_JSON) 2>/dev/null)
export GREENNODE_CLIENT_SECRET ?= $(shell jq -r '.client_secret // .clientSecret // .iam.client_secret // empty' $(GN_JSON) 2>/dev/null)

.DEFAULT_GOAL := help

.PHONY: help test lint run creds deploy redeploy status health logs endpoint destroy

help: ## Show this help
	@echo "EventBuddy targets:"
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Deploy config (override inline): RUNTIME_NAME=$(RUNTIME_NAME) FLAVOR=$(FLAVOR) ENV_FILE=$(ENV_FILE) PLATFORM=$(PLATFORM)"

# ---- local dev (run from repo root) ----
test: ## Run unit tests
	cd $(ROOT) && $(PY) -m pytest -q

lint: ## Run ruff
	cd $(ROOT) && $(VENV)/bin/ruff check src/ tests/

run: ## Run the app locally on :8080
	cd $(ROOT) && $(VENV)/bin/uvicorn eventbuddy.main:app --host 0.0.0.0 --port 8080

# ---- deploy (GreenNode AgentBase) ----
creds: ## Store GreenNode IAM client_id + secret (interactive, secret hidden)
	@bash $(ROOT)/deployment/setup_creds.sh

deploy: ## Build, push, and create/update the runtime, then health-check
	@bash $(ROOT)/deployment/deploy_agentbase.sh

redeploy: deploy ## Alias for deploy (idempotent: updates if the runtime exists)

status: ## Show runtime status (RUNTIME_NAME)
	@id=$$(bash $(SCRIPTS)/runtime.sh list --size 100 | jq -r --arg n "$(RUNTIME_NAME)" '.listData[]?|select(.name==$$n)|.id' | head -1); \
	  [ -n "$$id" ] && bash $(SCRIPTS)/runtime.sh get $$id | jq '{name,status,id}' || echo "No runtime named $(RUNTIME_NAME)"

endpoint: ## Print the DEFAULT endpoint URL
	@id=$$(bash $(SCRIPTS)/runtime.sh list --size 100 | jq -r --arg n "$(RUNTIME_NAME)" '.listData[]?|select(.name==$$n)|.id' | head -1); \
	  [ -n "$$id" ] && bash $(SCRIPTS)/runtime.sh endpoints list $$id | jq -r '.listData[]?|select((.name//""|ascii_downcase)=="default")|.url' || echo "No runtime named $(RUNTIME_NAME)"

health: ## curl the deployed /health endpoint
	@url=$$($(MAKE) -s endpoint); \
	  [ -n "$$url" ] && { echo "GET $${url%/}/health"; curl -s -w "\nHTTP %{http_code}\n" $${url%/}/health; } || echo "No endpoint yet"

logs: ## Tail runtime logs via the runtime script
	@id=$$(bash $(SCRIPTS)/runtime.sh list --size 100 | jq -r --arg n "$(RUNTIME_NAME)" '.listData[]?|select(.name==$$n)|.id' | head -1); \
	  ep=$$(bash $(SCRIPTS)/runtime.sh endpoints list $$id | jq -r '.listData[0]?.id'); \
	  bash $(SCRIPTS)/runtime.sh endpoints logs $$id $$ep

destroy: ## Delete the runtime (irreversible — prompts for confirmation)
	@read -p "Delete runtime '$(RUNTIME_NAME)' and all endpoints? type yes: " a; \
	  [ "$$a" = "yes" ] || { echo "aborted"; exit 1; }; \
	  id=$$(bash $(SCRIPTS)/runtime.sh list --size 100 | jq -r --arg n "$(RUNTIME_NAME)" '.listData[]?|select(.name==$$n)|.id' | head -1); \
	  [ -n "$$id" ] && bash $(SCRIPTS)/runtime.sh delete $$id || echo "nothing to delete"

# ensure ~/.local/bin (jq) is visible to recipes
export PATH := $(HOME)/.local/bin:$(PATH)
