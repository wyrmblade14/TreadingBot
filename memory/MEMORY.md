# Memory Index

- [User Profile](user_profile.md) — Beginner trader, no stock market knowledge, wants guidance, prefers Python, Zerodha/NSE, start with paper trading
- [What Has Been Built](project_built.md) — Phases 1–6 complete, live broker still deferred, fundamentals-ranked watchlist added, current suite: 275 passing tests
- [Technical Lessons Learned](lessons_learned.md) — Python 3.14 pitfalls, yfinance compatibility, scheduler restart safety, VIX direction bias, fundamentals watchlist fail-open design, repo structure boundaries
- [Planned Phases](project_planned.md) — Remaining Phase 6b live broker work, Phase 7 paper period, Phase 8 go-live constraints
- [Ideas & Improvements](ideas_and_improvements.md) — Living backlog with completed fundamentals watchlist and scheduler watchlist refactor entries
- [Deployment Target](deployment_target.md) — Oracle Cloud, unattended for months at a time; design for zero human intervention

---

## 🔄 Session Sync (Cross-Agent Status)
*Last update: 2026-04-12*

| Agent | Current Task | Status |
|---|---|---|
| **Gemini CLI** | Idle | Standby |
| **Claude Code** | Idle | Standby |
| **Codex** | Idle | Standby |

### 📝 Latest Context (Handoff Note)
**Last Agent:** Gemini CLI
**Completed:** 
1. Walk-Forward Backtesting (#4) implemented with CLI script and tests.
2. Sector Breadth Risk Filter (#18) implemented (Rule 12) with 5-min caching.
3. Shared Memory Architecture (Sync Protocol) established across all agent configs.
**Next Recommended Step:** Implement GTT (Good Till Triggered) orders (#6) to ensure stop-losses survive bot crashes in live/paper mode.

**Active Locks:** None
