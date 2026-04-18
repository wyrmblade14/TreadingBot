# TreadingBot — local-first commands
#
# ── Kite Auth ─────────────────────────────────────────────────────────────────
#   make login          — auto headless login (needs ZERODHA_* vars in .env)
#   make login-manual   — browser-based fallback (paste redirect URL)
#
# ── Docker — run bot ──────────────────────────────────────────────────────────
#   make up             — first-time: setup .env + build + start all containers
#   make bot            — restart only the bot container (fast after code change)
#   make down           — stop all containers
#   make logs           — follow bot logs live
#   make build          — rebuild all images
#   make shell          — open bash in the bot container
#   make db             — open psql shell in the postgres container
#
# ── Backtesting ───────────────────────────────────────────────────────────────
#   make backtest SYMBOL=RELIANCE
#   make backtest SYMBOL=RELIANCE STRATEGY=ema_crossover
#   make backtest SYMBOL=RELIANCE START=2024-01-01 END=2024-12-31
#   make backtest-all SYMBOL=RELIANCE        — all 6 strategies, comparison table
#   make backtest-wf  SYMBOL=RELIANCE        — walk-forward (6m train / 2m test)
#   make backtest-symbols                    — list symbols with assigned strategies
#   make weekly-review                       — backtest top 25 fundamentals, lock to approved_symbols.json
#   make weekly-review TOP=30 OPTIMIZE=1     — wider universe + Bayesian parameter optimization
#   make weekly-review DRY_RUN=1             — dry run, nothing written to disk
#
# ── Dev ───────────────────────────────────────────────────────────────────────
#   make test           — run the full pytest suite
#   make clean          — remove caches and build artifacts

SYMBOL   ?= RELIANCE
STRATEGY ?=
START    ?= 2023-01-01
END      ?= 2024-12-31

.PHONY: login login-manual up bot down logs build shell db \
        backtest backtest-all backtest-wf backtest-symbols weekly-review \
        test clean

# ── Kite Auth ─────────────────────────────────────────────────────────────────

login:
	@echo "Attempting automated Kite login..."
	python3 scripts/auto_kite_login.py && \
	  ( echo "Restarting bot to pick up new token..."; \
	    docker compose restart bot watchdog; \
	    echo "Done." ) || \
	  ( echo "Auto-login failed — falling back to manual login..."; \
	    $(MAKE) login-manual )

login-manual:
	python3 scripts/kite_login.py
	@echo "Restarting bot to pick up new token..."
	docker compose restart bot watchdog
	@echo "Done. Bot is running with fresh Kite token."

# ── Docker ────────────────────────────────────────────────────────────────────

up:
	python3 scripts/setup_env.py
	docker compose up -d
	@echo ""
	@echo "  Bot:        docker compose logs -f bot"
	@echo "  Dashboard:  http://localhost:3000"
	@echo "  API:        http://localhost:8000"
	@echo ""

bot:
	docker compose restart bot watchdog
	@echo "Bot restarted. Follow logs with: make logs"

down:
	docker compose down

logs:
	docker compose logs -f bot

build:
	docker compose build --parallel

shell:
	docker compose exec bot bash

db:
	docker exec -it treadingbot_postgres psql -U $${POSTGRES_USER:-treadingbot} -d $${POSTGRES_DB:-treadingbot}

# ── Backtesting ───────────────────────────────────────────────────────────────

backtest:
	@source .venv/bin/activate 2>/dev/null || true; \
	python3 scripts/run_backtest.py \
	  --symbol $(SYMBOL) \
	  $(if $(STRATEGY),--strategy $(STRATEGY),) \
	  --start $(START) --end $(END) --open

backtest-all:
	@source .venv/bin/activate 2>/dev/null || true; \
	python3 scripts/run_backtest.py --symbol $(SYMBOL) --all-strategies \
	  --start $(START) --end $(END)

backtest-wf:
	@source .venv/bin/activate 2>/dev/null || true; \
	python3 scripts/run_backtest.py --symbol $(SYMBOL) --walk-forward \
	  --start $(START) --end $(END)

backtest-symbols:
	@source .venv/bin/activate 2>/dev/null || true; \
	python3 scripts/run_backtest.py --list-symbols

weekly-review:
	@source .venv/bin/activate 2>/dev/null || true; \
	python3 scripts/assign_strategies.py \
	  $(if $(TOP),--top $(TOP),) \
	  $(if $(OPTIMIZE),--optimize,) \
	  $(if $(DRY_RUN),--dry-run,)

# ── Dev ───────────────────────────────────────────────────────────────────────

test:
	python3 -m pytest tests/ -v

clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.py[co]" -delete 2>/dev/null; true
	rm -rf .pytest_cache .coverage htmlcov/ web/.next/
	@echo "Done."
