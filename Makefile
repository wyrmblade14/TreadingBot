# TreadingBot — common tasks
#
# Usage:
#   make up       — first-time start (generate credentials + start all containers)
#   make deploy   — rebuild image + redeploy after code changes (postgres untouched)
#   make down     — stop all containers
#   make logs     — follow bot logs
#   make restart  — restart all containers
#   make db       — open a psql shell inside the postgres container
#   make test     — run the full test suite
#   make migrate  — migrate existing SQLite data into PostgreSQL (run once)
#   make clean    — remove temporary files, caches, and build artifacts
#
# Manual token refresh (only needed if automated login is not configured):
#   make login    — automated headless login (needs ZERODHA_* vars in .env)
#   make login-manual — browser-based login (paste redirect URL)
#   make telegram — Telegram-based login (tap URL on your phone)
#
# Oracle Cloud (optional — free tier):
#   make oci-provision      — create Oracle Cloud VM, VCN, security rules
#   make oci-setup-services — create Object Storage bucket + OCI Vault (free)
#   make oci-vault-push     — push .env secrets into OCI Vault (run once after setup)
#   make oci-backup / oci-backups / db-restore — manual backup/restore controls
#
# NOTE: With ZERODHA_USER_ID / ZERODHA_PASSWORD / ZERODHA_TOTP_SECRET set in
# .env, the bot auto-refreshes the Kite token at 8:30 AM every trading day.
# No daily intervention needed.

PROD_COMPOSE = docker-compose -f docker-compose.yml -f docker-compose.prod.yml

.PHONY: up down prod-up prod-deploy oci-provision oci-setup-services oci-ssh oci-destroy oci-backup oci-backups oci-vault-push db-restore login login-manual telegram deploy logs restart db test migrate clean build-all

oci-provision:
	@bash scripts/oci_provision.sh $(ARGS)

oci-ssh:
	@IP=$$(oci compute instance list-vnics \
	  --instance-id $$(oci compute instance list \
	    --compartment-id $$(grep tenancy ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ') \
	    --display-name TreadingBot --lifecycle-state RUNNING \
	    --query 'data[0].id' --raw-output) \
	  --query 'data[0]."public-ip"' --raw-output 2>/dev/null); \
	echo "Connecting to $$IP..."; \
	ssh ubuntu@$$IP

oci-setup-services:
	@bash scripts/oci_setup_free_services.sh $(ARGS)

oci-backup:
	@bash scripts/backup_to_oci.sh

oci-backups:
	@oci os object list --bucket-name treadingbot-backups \
	  --query 'data[*].{name:name,size:"size"}' --output table 2>/dev/null \
	  || echo "OCI CLI not configured or bucket not created yet."

oci-vault-push:
	@echo "Pushing .env secrets to OCI Vault..."
	python3 scripts/oci_vault_push.py

db-restore:
	@bash scripts/db_restore.sh

oci-destroy:
	@echo "WARNING: This will TERMINATE the TreadingBot instance and all data."
	@read -p "Type 'destroy' to confirm: " CONFIRM; \
	if [ "$$CONFIRM" = "destroy" ]; then \
	  INSTANCE_ID=$$(oci compute instance list \
	    --compartment-id $$(grep tenancy ~/.oci/config | head -1 | cut -d= -f2 | tr -d ' ') \
	    --display-name TreadingBot --lifecycle-state RUNNING \
	    --query 'data[0].id' --raw-output); \
	  oci compute instance terminate --instance-id $$INSTANCE_ID --force; \
	  echo "Instance terminated."; \
	else \
	  echo "Aborted."; \
	fi

prod-up:
	python3 scripts/setup_env.py
	$(PROD_COMPOSE) up -d --build
	@echo ""
	@echo "Production stack running."
	@echo "Access via Tailscale only — no public internet exposure."
	@echo ""
	@TSHOST=$$(tailscale ip -4 2>/dev/null | head -1); \
	  if [ -n "$$TSHOST" ]; then \
	    echo "  Dashboard → http://$$TSHOST"; \
	    echo "  API health → http://$$TSHOST/api/health"; \
	  else \
	    echo "  Tailscale not running — install it: curl -fsSL https://tailscale.com/install.sh | sh"; \
	    echo "  Then: sudo tailscale up && make prod-up"; \
	  fi
	@echo ""

prod-deploy:
	$(PROD_COMPOSE) build --parallel
	$(PROD_COMPOSE) up -d --no-deps bot watchdog dashboard-api react-dashboard nginx
	@echo "Redeployed. Postgres untouched."

login:
	@echo "Attempting automated Kite login..."
	python3 scripts/auto_kite_login.py && \
	  ( echo "Restarting containers to pick up new token..."; \
	    docker-compose restart bot watchdog; \
	    echo "Done." ) || \
	  ( echo "Auto-login failed — falling back to manual login..."; \
	    $(MAKE) login-manual )

login-manual:
	python3 scripts/kite_login.py
	@echo "Restarting bot to pick up new token..."
	docker-compose restart bot watchdog
	@echo "Done. Bot is running with fresh Kite token."

telegram:
	@echo "Starting Telegram command daemon (send /kite_login from your phone)..."
	python3 scripts/telegram_daemon.py

deploy:
	docker-compose build --parallel bot watchdog dashboard-api react-dashboard
	docker-compose up -d --no-deps bot watchdog dashboard-api react-dashboard

build-all:
	docker-compose build --parallel

up:
	python3 scripts/setup_env.py
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f bot

restart:
	docker-compose restart

db:
	docker exec -it treadingbot_postgres psql -U $${POSTGRES_USER:-treadingbot} -d $${POSTGRES_DB:-treadingbot}

test:
	python3 -m pytest tests/ -v

migrate:
	python3 scripts/setup_env.py
	docker-compose up -d postgres
	@echo "Waiting for postgres to be ready (user + db created)..."
	@until docker exec treadingbot_postgres psql -U $${POSTGRES_USER:-treadingbot} -d $${POSTGRES_DB:-treadingbot} -c "SELECT 1" -q 2>/dev/null; do sleep 1; done
	@echo "Postgres is ready."
	python3 scripts/migrate_sqlite_to_postgres.py

clean:
	@echo "Cleaning up temporary files and caches..."
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.py[co]" -delete
	find . -type f -name "*$py.class" -delete
	rm -rf .pytest_cache .coverage htmlcov/ .next/ web/.next/ web/node_modules/
	@echo "Done."
