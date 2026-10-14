# Shortcuts for the docker compose stack. Run `make help` for the list.
SHELL := /bin/bash
COMPOSE := docker compose  # finds infrastructure/docker-compose.yml via COMPOSE_FILE in .env
# One-shot services that must exit 0 for the stack to count as up (grows in later phases)
INIT_JOBS := rustfs-init
-include .env
export

.DEFAULT_GOAL := help
.PHONY: help env up down reset ps logs config psql s3

help:  ## List targets
	@grep -hE '^[a-z0-9-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

env:  ## Create .env from .env.example with random secrets (refuses to overwrite)
	@test ! -f .env || { echo ".env already exists; delete it first to regenerate"; exit 1; }
	@sed -e "s/change-me/__SECRET__/" .env.example | while IFS= read -r line; do \
	  echo "$${line/__SECRET__/$$(openssl rand -hex 16)}"; done > .env
	@echo "wrote .env"

up:  ## Start the stack and wait until every service is healthy (init jobs must exit 0)
	$(COMPOSE) up -d --wait
	@infrastructure/scripts/wait-init.sh $(INIT_JOBS)
	@$(COMPOSE) ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

down:  ## Stop and remove containers (volumes, i.e. data, are kept)
	$(COMPOSE) down

reset:  ## Stop and DELETE all data volumes (Postgres + RustFS)
	$(COMPOSE) down -v --remove-orphans

ps:  ## Show all services, including finished init jobs
	@$(COMPOSE) ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'

logs:  ## Follow logs: make logs [S=service]
	$(COMPOSE) logs -f $(S)

config:  ## Validate infrastructure/docker-compose.yml + .env and print the resolved config
	$(COMPOSE) config

psql:  ## Open psql as the admin user: make psql [DB=lakekeeper]
	$(COMPOSE) exec postgres psql -U "$$POSTGRES_USER" -d $(or $(DB),postgres)

s3:  ## Run an AWS CLI s3 command against RustFS: make s3 ARGS="ls s3://landing"
	$(COMPOSE) run --rm --no-deps --entrypoint aws rustfs-init s3 $(or $(ARGS),ls)
