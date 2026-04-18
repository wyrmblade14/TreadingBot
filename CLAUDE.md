# CLAUDE.md (AI Entry Point)

This project uses a **Universal AI Agent Protocol**. 

**MANDATORY FIRST STEPS:**
1.  Read `AGENT_RULES.md` immediately to understand the session-tracking and handoff protocol.
2.  Follow the rules in `AGENT_RULES.md` to check `memory/MEMORY.md` for the latest context.
3.  Consult `AGENTS.md` for all technical details, commands, and architecture.

## Commands Reference
(See `AGENTS.md` for full command list and architecture details).

```bash
# Quick reference
source .venv/bin/activate
python -m pytest tests/ -v
streamlit run dashboard/app.py
make weekly-review OPTIMIZE=1          # weekend: backtest + optimize top 25, lock symbols
python scripts/assign_strategies.py --top 25 --optimize  # same as above, verbose
```
