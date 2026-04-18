# Memory Index

- [User Profile](user_profile.md) — Beginner trader, no stock market knowledge, wants guidance, prefers Python, Zerodha/NSE, start with paper trading
- [What Has Been Built](project_built.md) — Phases 1–7 complete, per-symbol strategy routing + per-symbol params, 374 passing tests
- [Technical Lessons Learned](lessons_learned.md) — Paper slippage pitfall, Bayesian optimization benefits, Python 3.14 pitfalls, yfinance compatibility, scheduler restart safety
- [Planned Phases](project_planned.md) — Remaining Phase 6b live broker work, Phase 7 paper period, Phase 8 go-live constraints
- [Ideas & Improvements](ideas_and_improvements.md) — Living backlog with completed fundamentals watchlist and scheduler watchlist refactor entries
- [Deployment Target](deployment_target.md) — Oracle Cloud, unattended for months at a time; design for zero human intervention

---

## 🔄 Session Sync (Cross-Agent Status)
*Last update: 2026-04-18*

| Agent | Current Task | Status |
|---|---|---|
| **Gemini CLI** | Idle | Standby |
| **Claude Code** | Idle | Standby |
| **Codex** | Idle | Standby |

### 📝 Latest Context (Handoff Note)
**Last Agent:** Claude Code
**Completed (Apr 18):**
1. **Weekend Review / Lock-In Workflow** — unified strategy assignment + optimization into one command. `scripts/assign_strategies.py --top 25 --optimize` is the single weekend entry point.
2. **`config/approved_symbols.json`** — new locked trading universe file (7-day expiry). Bot trades ONLY these symbols + their locked strategies during weekdays.
3. **Watchlist Priority** — `scheduler/watchlist.py` now checks `approved_symbols.json` first (`source="approved_weekly"`), falls back to fundamentals, then static NIFTY50.
4. **Strategy Resolution Priority 0** — `_get_strategies_for_symbol()` in `job_runner.py` now checks `approved_symbols.json` before all other sources.
5. **Saturday 10 AM IST cron** — `weekend_review_job()` auto-runs `assign_strategies.py --optimize` every Saturday.
6. **Deleted** `scripts/weekly_review.py` (was duplicate of assign_strategies.py).
7. Tests: 374 passing (unchanged).

**Next Recommended Step:** Run `make weekly-review OPTIMIZE=1` on a weekend to populate `approved_symbols.json`, then start paper trading from Monday with the locked universe.

**Active Locks:** None
