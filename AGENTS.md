# TreadingBot — Agent Master Reference

## 🤖 Mandatory Protocol
Before doing *anything* else, all AI agents MUST read and follow the **[AGENT_RULES.md](AGENT_RULES.md)** for session tracking and handoff.

## 🧠 Project Context
- **User**: Stock market beginner. Always explain concepts. Paper-first, never rush to live.
- **Broker**: Zerodha (Kite Connect). Market: NSE India. Instruments: NIFTY50 cash segment only.
- **Mode**: `TRADING_MODE=paper` in `.env`. Switch to `live` only after 30+ days paper success.
- **Language**: Python 3.14, venv at `venv/` (`source venv/bin/activate`)

## Critical Tech Decisions
| Decision | Reason |
|---|---|
| `ta` not `pandas-ta` | pandas-ta needs numba; numba doesn't support Python 3.14 |
| `pd.concat` not `df[col]=` | Avoids pandas CoW FutureWarning in indicator compute() |
| `BaseBroker` interface | Paper↔live swap = one config line, zero other changes |
| ATR-based stop-loss | Sits outside normal noise; fallback = 0.5% of price |
| ORB target = max(projected, entry+2×ATR) | Fixes edge case when price already exceeds projection |
| EMA target = 3.0×ATR (not 2.5×ATR) | 3.0/1.5 = 2.0:1 RR exactly — 2.5/1.5 = 1.67 failed minimum |
| Backtest intraday: global_idx not day-slice | Strategies need 26+ candles; day-only slice = 0 trades |
| Backtest tiered intervals: 5m/1h/1d | yfinance limits: 5m=60d, 1h=730d, 1d=unlimited |
| `BackgroundScheduler` for bot_controller | `BlockingScheduler` would block the main thread |
| VWAP `_is_daily`: compare index to normalize() | floor("D") == normalize() always; must compare original to floor |

## Architecture Flow
```
Fundamentals/catalysts → scheduler/watchlist.py
Market data → indicators/ → strategies/ → RiskManager.evaluate()
                                                    ↓ approved
                                         OrderManager.execute_signal()
                                                    ↓
                                     PaperBroker / KiteBroker
                                                    ↓
                                    TradeLogger (logs/trades.db)
                                                    ↓
                                    Portfolio → Dashboard
```

## Build Status
| Phase | Status | Tests | Key files |
|---|---|---|---|
| 1 Foundation | ✅ Done | 20 | config/, data/, indicators/ |
| 2 Strategies + Risk | ✅ Done | 43 | strategies/, risk/ |
| 3 Paper Trading | ✅ Done | 23 | broker/, execution/ |
| 4 Backtesting | ✅ Done | 21 | backtesting/engine.py, performance.py, report.py |
| 5 Dashboard | ✅ Done | — | dashboard/app.py, dashboard/views/, analysis/ |
| 6 Scheduler + Notifications | ✅ Done | — | scheduler/job_runner.py, scheduler/watchlist.py, notifications/ |
| Fundamentals Watchlist | ✅ Done | 15 | analysis/fundamental_selector.py, scheduler/watchlist.py |
| Build & Ops Optimization | ✅ Done | — | Dockerfile, web/Dockerfile, .dockerignore, Makefile |
| 6b Live Kite | 🔲 Deferred | — | data/kite_auth.py, data/kite_feed.py, data/kite_ticker.py, broker/kite_broker.py |
| 7 Paper Period | 🔲 | — | 30+ trading days, win rate >45% |
| 8 Go Live | 🔲 | — | `TRADING_MODE=live`, start ₹10k–₹20k |

**Total tests: 272 passing, 0 failures**

## Key Constants (config/settings.py)
```
Market: 9:15–15:30 IST | Blackout: <9:20 | No new entries: >14:30 | Square-off: 15:15
Risk: 1%/trade | Daily loss halt: 3% | Max positions: 3 | Min RR: 2:1 | Consec losses halt: 3→1hr
Zerodha costs: ₹20/order + STT 0.025% sell + exchange 0.00325% + GST 18% + SEBI ₹10/cr + stamp 0.003% buy
Slippage: 0.2%/side | Virtual capital: ₹1,00,000
```

## Risk Gates (risk/risk_manager.py)
1. qty = floor((capital×1%) / risk_per_share)
2. Stop-loss required on every trade
3. Min 2:1 reward:risk
4. Daily loss >3% → halt
5. 3 consecutive losses → 1hr pause
6. No entries before 9:20 AM
7. No new entries after 2:30 PM
8. Max 3 open positions
9. No duplicate symbol (no averaging down)
10. Signal sanity: SL < entry < target (BUY)
11. Earnings blackout blocks new entries
12. VIX/direction safety suppresses unsafe sides

## Symbol Formats
- Kite Connect: `"RELIANCE"` — no suffix
- yfinance: `"RELIANCE.NS"` — .NS for NSE
- Mapping in `data/instruments.py`: `KITE_TO_YF`, `YF_TO_KITE`

## Indicator API (using `ta` library)
```python
ta.trend.EMAIndicator(close, window=N).ema_indicator()
ta.momentum.RSIIndicator(close, window=14).rsi()
ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9).macd()  # / .macd_signal() / .macd_diff()
```

## Test Mock Pattern (RiskManager time gates)
```python
with patch("risk.risk_manager.datetime") as mock_dt:
    mock_dt.now.return_value = datetime.fromisoformat("2024-01-02 09:25:00+05:30")
```

## Phase 4 — Backtesting (DONE)
- `backtesting/engine.py`: tiered intervals (5m≤55d, 1h≤700d, 1d>700d), global_idx no-lookahead
- `backtesting/performance.py`: Sharpe, max drawdown, win rate, profit factor
- `backtesting/report.py`: Plotly HTML equity curve + drawdown shading + trade markers
- `scripts/run_backtest.py`: CLI `--symbol`, `--strategy`, `--start`, `--end`

## Phase 5 — Dashboard (DONE)
- React (Next.js) at `localhost:3000` — `cd web && npm run dev`
- Python JSON API at `localhost:8000` — `python scripts/run_react_dashboard.py`
- Pages: Home, Journal, Compare, Signals, Backtest, Replay, Analysis, Fundamentals, Bot Monitor, Settings
- Legacy Streamlit (`dashboard/`) kept for reference but not deployed or used

## Phase 6 — Scheduler + Notifications (DONE, live Kite deferred)
- `scheduler/job_runner.py`: APScheduler IST jobs (9:00 pre-market → 15:30 report)
- `scheduler/watchlist.py`: fundamentals-ranked daily watchlist + static fallback + fundamental judgment lookup
- `scheduler/bot_controller.py`: BackgroundScheduler singleton, start/stop/event-log for UI
- `notifications/telegram_notifier.py`: trade alerts + daily report to Telegram
- `data/nse_holidays.py`: NSE holiday calendar 2024–2026

## Phase 6b — Live Kite (Deferred)
- `data/kite_auth.py`, `data/kite_feed.py`, `data/kite_ticker.py`: built Kite auth/feed/ticker pieces
- `broker/kite_broker.py`: deferred live order execution
- Daily re-auth: **fully automated** — see "Zero-Touch Daily Operations" below

## Oracle Cloud Deployment via OCI CLI (Fully Automated)

**One command to provision everything** (VCN, subnet, firewall, instance, Docker, Tailscale):

```bash
# 1. Install OCI CLI (once)
pip install oci-cli
oci setup config          # follow prompts — needs tenancy OCID, user OCID, API key

# 2. Provision
make oci-provision        # ~5 min, prints SSH command when done

# 3. SSH in, activate Tailscale, clone repo, set .env, deploy
make oci-ssh              # connects automatically
```

Other OCI commands:
```bash
make oci-ssh              # SSH into the instance
make oci-destroy          # terminate instance (asks for confirmation)
make oci-provision ARGS="--compartment-id ocid1.compartment..."  # specific compartment
```

The provisioning script (`oci/provision.sh`) is idempotent — safe to run multiple times.

## Oracle Cloud Deployment (One-Time Setup)

**Step 1 — Provision Oracle Free Tier instance**
- Shape: `VM.Standard.A1.Flex` (Ampere ARM) — 4 OCPU + 24 GB RAM, always free
- OS: Ubuntu 22.04 LTS
- VCN Security List: **delete all inbound rules** — block everything from internet

**Step 2 — Install Tailscale (private VPN)**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
# Open the auth URL on your phone/laptop to approve
```
Install Tailscale on your phone and laptop too. All devices share a private network.

**Step 3 — Install Docker**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
sudo apt-get install -y docker-compose-plugin
```

**Step 4 — Clone and configure**
```bash
git clone <your-repo> TreadingBot && cd TreadingBot
cp .env.example .env
```
Edit `.env` — set every value including:
```
ZERODHA_USER_ID=...          # enables auto-login — no manual token refresh ever
ZERODHA_PASSWORD=...
ZERODHA_TOTP_SECRET=...      # base32 key from Zerodha Console → Security
NEXT_PUBLIC_DASHBOARD_API_URL=http://$(tailscale ip -4)  # your Tailscale IP, no port
```

**Step 5 — Deploy**
```bash
make prod-up
```
Builds images, starts all containers, prints your Tailscale dashboard URL. Done.

**Access from any Tailscale device:**
- Dashboard: `http://100.x.x.x` (Tailscale IP)
- API health: `http://100.x.x.x/api/health`
- Public internet: cannot reach anything — VCN blocks all inbound

**After first deploy:**
- Code changes: `make prod-deploy` (redeploys, postgres untouched)
- Server reboots: `restart: unless-stopped` brings everything back automatically
- Daily token: fully automated at 8:30 AM via TOTP — no action needed

## Zero-Touch Daily Operations
Set these once in `.env`; the bot handles everything after:

```
ZERODHA_USER_ID=AB1234
ZERODHA_PASSWORD=your_password
ZERODHA_TOTP_SECRET=JBSWY3DPEHPK3PXP   # base32 seed from Zerodha Console → Security
```

**What runs automatically:**
| Time (IST) | What happens |
|---|---|
| Startup | `auto_kite_login.py` runs — refreshes token if expired, skips if valid |
| 08:30 | `kite_login_reminder` cron — attempts auto-login, confirms via Telegram |
| 09:00 | `pre_market_scan` — NIFTY breadth, builds watchlist |
| 09:15 | `market_open` — resets risk state, logs capital |
| 09:20–14:25 (every 1m) | Signal scan, risk check, paper executions |
| 14:30 | `stop_new_entries` |
| 15:15 | `square_off_all` — closes all positions |
| 15:30 | `daily_report` — P&L summary via Telegram |
| 15:35 | `auto_shutdown` |

**Fallback chain (if auto-login fails):**
1. Try headless HTTP login with TOTP (`scripts/auto_kite_login.py`)
2. Send `/kite_login` Telegram prompt (tap URL on phone)
3. Manual `make login` → paste redirect URL

**Docker restart policy:** `restart: unless-stopped` on all containers — survives server reboots.  
**Health check:** bot container pgrep'd every 60s — auto-restart if process dies.

## Memory Files
- `memory/MEMORY.md` — index
- `memory/project_built.md` — phase details + key facts per phase
- `memory/lessons_learned.md` — gotchas, non-obvious decisions
- `memory/project_planned.md` — phases 4–8 detail
- `memory/ideas_and_improvements.md` — living ideas backlog (read every session)

## Skills

All skills live in `skills/` (universal — usable by any AI agent).  
Claude Code users invoke via `/skill-name`. Other agents: read `skills/<name>.md` directly.

| Skill | File | What it does |
|---|---|---|
| `run-tests` | `skills/run-tests.md` | Run full test suite + explain failures |
| `backtest` | `skills/backtest.md` | Run standard or walk-forward backtest |
| `dashboard` | `.claude/commands/dashboard.md` | Start React dashboard (Next.js + API) |
| `add-strategy` | `skills/add-strategy.md` | Add a new trading strategy end-to-end |
| `trade-log` | `.claude/commands/trade-log.md` | Show trade history from DB |
| `paper-trade` | `.claude/commands/paper-trade.md` | Start / explain paper trading session |
| `ideas` | `.claude/commands/ideas.md` | Review ideas & improvements backlog |
| `risk-audit` | `skills/risk-audit.md` | Audit all 12 risk gates + current state |
| `signal-debug` | `skills/signal-debug.md` | Trace why a signal fired or was blocked |
| `kite-live` | `skills/kite-live.md` | Kite auth, GTT, live switchover guide |
| `strategy-perf` | `skills/strategy-perf.md` | Analyse paper trade win rates + degradation |
| `go-live` | `skills/go-live.md` | Full Phase 7→8 go-live readiness checklist |
| `watchlist` | `skills/watchlist.md` | Manage fundamentals-ranked universe |
| `market-data` | `skills/market-data.md` | Fix yfinance/Kite data + NSE holiday issues |
| `gtt-orders` | `skills/gtt-orders.md` | Implement GTT crash-safe stop orders |
| `brainstorm` | `skills/brainstorm.md` | NSE market expert — accuracy improvement ideas |
| `self-learn` | `skills/self-learn.md` | Self-learning: feature store → ML classifier → Bayesian param optimizer |
