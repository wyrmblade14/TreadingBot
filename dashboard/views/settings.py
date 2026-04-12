"""
Settings page — view and understand the bot's configuration.

This page shows all active settings in a readable format.
For safety, actual live-mode settings CANNOT be changed here
— you must edit config/settings.py manually.

This is intentional: live trading mode requires deliberate action,
not an accidental toggle click.
"""

from __future__ import annotations

import streamlit as st

import config.settings as cfg


def render() -> None:
    st.title(":material/settings: Settings & Configuration")
    st.caption("Read-only view of all active settings. Edit `config/settings.py` to change values.")

    # ── Trading mode ──────────────────────────────────────────────────
    st.subheader("Trading Mode")
    mode = getattr(cfg, "TRADING_MODE", "paper")
    if mode == "paper":
        st.success("**PAPER TRADING MODE** — No real money is at risk. All orders are simulated.")
    else:
        st.error("**LIVE TRADING MODE** — Real orders will be placed with Zerodha!")
        st.warning("Switch back to paper mode by setting `TRADING_MODE = 'paper'` in `config/settings.py`.")

    st.markdown("---")

    # ── Market hours ──────────────────────────────────────────────────
    st.subheader("Market Hours (IST)")
    cols = st.columns(3)
    cols[0].metric("Market Open",       str(getattr(cfg, "MARKET_OPEN",        "09:15")))
    cols[1].metric("No New Entries After", str(getattr(cfg, "NO_NEW_ENTRIES_TIME", "14:30")))
    cols[2].metric("Force Square-off At",  str(getattr(cfg, "SQUAREOFF_TIME",       "15:15")))

    st.markdown("---")

    # ── Risk parameters ───────────────────────────────────────────────
    st.subheader("Risk Management Parameters")
    r1, r2, r3 = st.columns(3)
    r1.metric("Capital Risk per Trade",   f"{getattr(cfg, 'RISK_PER_TRADE_PCT', 1.0):.1f}%")
    r2.metric("Max Daily Loss Limit",     f"{getattr(cfg, 'MAX_DAILY_LOSS_PCT', 3.0):.1f}%")
    r3.metric("Min Reward:Risk Ratio",    f"{getattr(cfg, 'MIN_REWARD_RISK_RATIO', 2.0):.1f}x")

    r4, r5, r6 = st.columns(3)
    r4.metric("Max Open Positions",      str(getattr(cfg, 'MAX_OPEN_POSITIONS', 3)))
    r5.metric("Consecutive Loss Pause",  f"{getattr(cfg, 'MAX_CONSECUTIVE_LOSSES', 3)} losses → pause")
    r6.metric("ATR Stop Multiplier",     f"1.5×")

    st.markdown("---")

    # ── Capital settings ──────────────────────────────────────────────
    st.subheader("Capital")
    st.metric("Starting Capital", f"₹{getattr(cfg, 'VIRTUAL_CAPITAL', 100_000):,.0f}")

    st.markdown("---")

    # ── Brokerage rates ───────────────────────────────────────────────
    st.subheader("Zerodha Brokerage Rates (used in paper simulation)")
    b1, b2, b3 = st.columns(3)
    b1.metric("Brokerage per Order",       f"₹{getattr(cfg, 'BROKERAGE_PER_ORDER', 20.0):.0f}")
    b2.metric("STT (intraday sell)",        f"{getattr(cfg, 'STT_INTRADAY_SELL', 0.00025)*100:.4f}%")
    b3.metric("Exchange Transaction Charge",f"{getattr(cfg, 'EXCHANGE_TRANSACTION_CHARGE', 0.0000325)*100:.5f}%")
    b4, b5, _ = st.columns(3)
    b4.metric("GST Rate",   f"{getattr(cfg, 'GST_RATE', 0.18)*100:.0f}%")
    b5.metric("Slippage",   f"{getattr(cfg, 'SLIPPAGE_PCT', 0.001)*100:.1f}%")

    st.markdown("---")

    # ── How to go live ────────────────────────────────────────────────
    with st.expander(":material/menu_book: How to switch to live trading (read this carefully first)"):
        st.markdown("""
### Before going live, make sure:
- [ ] You have paper traded for **at least 30 trading days** (about 6 weeks)
- [ ] Your win rate is consistently above **45%** in paper mode
- [ ] You understand every trade the bot made — no black boxes
- [ ] You have your Zerodha API key and secret set in `.env`
- [ ] You understand the daily auth token refresh requirement

### Steps to switch:
1. Edit `config/settings.py`:
   ```python
   TRADING_MODE = "live"   # change from "paper"
   ```
2. Set your Zerodha credentials in `.env`:
   ```
   KITE_API_KEY=your_key_here
   KITE_API_SECRET=your_secret_here
   ```
3. Run the daily auth script before market open to get a fresh access token.
4. **Start with ₹10,000–₹20,000 maximum**. Do NOT deploy full capital immediately.
5. Run paper mode in parallel for the first 2 weeks to compare results.

> The paper broker and live broker implement the same `BaseBroker` interface.
> Switching is just that one config line — no other code changes needed.
        """)
