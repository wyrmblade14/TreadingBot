# Memory Index

- [User Profile](user_profile.md) — Beginner trader, no stock market knowledge, wants guidance, prefers Python, Zerodha/NSE, start with paper trading
- [What Has Been Built](project_built.md) — Phases 1–7 complete, per-symbol strategy routing + per-symbol params, 374 passing tests
- [Technical Lessons Learned](lessons_learned.md) — Paper slippage pitfall, Bayesian optimization benefits, Python 3.14 pitfalls, yfinance compatibility, scheduler restart safety
- [Planned Phases](project_planned.md) — Remaining Phase 6b live broker work, Phase 7 paper period, Phase 8 go-live constraints
- [Ideas & Improvements](ideas_and_improvements.md) — Living backlog with completed fundamentals watchlist and scheduler watchlist refactor entries
- [Deployment Target](deployment_target.md) — Oracle Cloud, unattended for months at a time; design for zero human intervention

---

## 🔄 Session Sync (Cross-Agent Status)
*Last update: 2026-04-17*

| Agent | Current Task | Status |
|---|---|---|
| **Gemini CLI** | Idle | Standby |
| **Claude Code** | Idle | Standby |
| **Codex** | Idle | Standby |

### 📝 Latest Context (Handoff Note)
**Last Agent:** Claude Code
**Completed:**
1. Per-symbol strategy assignment: `SYMBOL_STRATEGY_MAP` / `SECTOR_STRATEGY_MAP` in `config/strategies.py` + `_get_strategies_for_symbol()` helper in `job_runner.py` (4-level priority lookup). `scripts/assign_strategies.py` backtests all 6 strategies per symbol (Kite 60-min data) and writes the winner to `param_history.json["strategy_assignment"]`.
2. Per-symbol strategy parameters extended to all 5 remaining strategies (`rsi_macd_combo`, `opening_range_breakout`, `vwap_bounce`, `trend_rider`, `bb_mean_reversion`). Each now has `_get_config(symbol)`, `_symbol_cache`, and `_init_indicators(params)` matching the EMA Crossover pattern.
3. `learning/param_optimizer.py` expanded with `optimize_*` methods for all 6 strategies + `optimize_all(symbol)` convenience wrapper. `job_runner.py` now calls `optimize_all()` instead of `optimize_ema_crossover()`.
4. Test suite: 374 passing (was 275). New test file: `tests/test_symbol_strategy_map.py` (16 tests).
**Next Recommended Step:** Run `scripts/assign_strategies.py --top 25` against live Kite data to populate initial strategy assignments. Then observe paper-trading results with per-symbol routing active.

**Active Locks:** None
