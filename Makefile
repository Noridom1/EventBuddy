# Thin forwarder — the real targets live in deployment/Makefile.
# Lets you run `make deploy`, `make test`, etc. from the repo root.
MAKEFLAGS += --no-print-directory

.PHONY: help test lint run creds deploy redeploy status health logs endpoint destroy
help test lint run creds deploy redeploy status health logs endpoint destroy:
	@$(MAKE) -C deployment $@

.DEFAULT_GOAL := help
