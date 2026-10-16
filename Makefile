# Shortcuts for the docker compose stack. Run `make help` for the list.
SHELL := /bin/bash
COMPOSE := docker compose  # finds infrastructure/docker-compose.yml via COMPOSE_FILE in .env
-include .env
export

.DEFAULT_GOAL := help
.PHONY: help env up down reset ps portal course logs config psql s3 lifecycle trino airflow dbt dct charts-check test

help:  ## List targets
	@grep -hE '^[a-z0-9-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | awk -F':.*## ' '{printf "  make %-13s %s\n", $$1, $$2}'

env:  ## Create .env from .env.example with random secrets (refuses to overwrite)
	@test ! -f .env || { echo ".env already exists; delete it first to regenerate"; exit 1; }
	@sed -e "s/change-me-fernet/__FERNET__/; s/change-me/__SECRET__/" .env.example | while IFS= read -r line; do \
	  line="$${line/__FERNET__/$$(openssl rand -base64 32 | tr '+/' '-_')}"; \
	  echo "$${line/__SECRET__/$$(openssl rand -hex 16)}"; done > .env
	@echo "wrote .env"

up:  ## Build (cached) and start the stack; waits until services are healthy and one-shot jobs exited 0
	$(COMPOSE) up -d --build --wait --remove-orphans
	@$(COMPOSE) ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

down:  ## Stop and remove containers (volumes, i.e. data, are kept)
	$(COMPOSE) down

reset:  ## Stop and DELETE all data volumes (Postgres + RustFS)
	$(COMPOSE) down -v --remove-orphans

ps:  ## Show all containers, including the finished one-shot jobs
	@$(COMPOSE) ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}\t{{.Ports}}'

portal:  ## Open the start page: every web UI in one place, with a reachability check
	@open infrastructure/portal.html 2>/dev/null || xdg-open infrastructure/portal.html

course:  ## Open the hands-on course: 16 lessons on this pipeline and data engineering
	@open course/index.html 2>/dev/null || xdg-open course/index.html

logs:  ## Follow logs: make logs [S=service]
	$(COMPOSE) logs -f $(S)

config:  ## Validate infrastructure/docker-compose.yml + .env and print the resolved config
	$(COMPOSE) config

psql:  ## Open psql as the admin user: make psql [DB=lakekeeper]
	$(COMPOSE) exec postgres psql -U "$$POSTGRES_USER" -d $(or $(DB),postgres)

s3:  ## Run an AWS CLI s3 command against RustFS: make s3 ARGS="ls s3://landing"
	@$(COMPOSE) run --rm -q aws s3 $(or $(ARGS),ls)

lifecycle:  ## Show the RustFS lifecycle rules that expire old files (set by setup)
	@{ echo "BUCKET RULE PREFIX DAYS STATUS"; for b in landing reports; do \
	  $(COMPOSE) run --rm -q aws s3api get-bucket-lifecycle-configuration --bucket $$b --output text \
	    --query 'Rules[].[ID, Filter.Prefix || `"*"`, Expiration.Days, Status]' | awk -v b=$$b '{print "s3://" b, $$0}'; \
	done; } | column -t

# $(value SQL), single-quoted for bash: the statement reaches Trino verbatim, so "<table>$$snapshots" works
trino:  ## Trino SQL shell on the iceberg catalog, or run one statement: make trino SQL="show schemas"
	@sql='$(subst ','\'',$(value SQL))'; \
	if [ -n "$$sql" ]; then $(COMPOSE) exec trino trino --catalog iceberg --execute "$$sql"; \
	else $(COMPOSE) exec trino trino --catalog iceberg; fi

airflow:  ## Airflow CLI in the airflow container: make airflow ARGS="dags list"
	$(COMPOSE) exec airflow airflow $(or $(ARGS),dags list)

dbt:  ## dbt in the airflow container (project dbt/ at /opt/dbt): make dbt ARGS="build -s +stg_logs"
	$(COMPOSE) exec -w /opt/dbt airflow /opt/dbt-venv/bin/dbt $(or $(ARGS),debug)

dct:  ## dbt Charts CLI in the charts container: make dct ARGS="render charts/fleet_overview.yml --format text"
	$(COMPOSE) exec -w /opt/dbt charts /opt/charts-venv/bin/dct $(or $(ARGS),--help)

charts-check:  ## Validate (strict) and render every board; non-zero exit if any board isn't publishable
	$(COMPOSE) exec -w /opt/dbt charts /opt/charts-venv/bin/python /opt/scripts/check_charts.py

test:  ## Unit tests of the ingestion package (fixtures only: no network, no services)
	cd ingest && uv run pytest -q
