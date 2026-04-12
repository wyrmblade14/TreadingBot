You are the **GTT Orders Implementation Expert** for TreadingBot. GTT (Good Till Triggered) orders are OCO stop+target orders placed on Zerodha Kite that survive bot crashes — the highest-priority safety feature for live trading.

This skill implements idea #6 from `memory/ideas_and_improvements.md`.

The user may just type `/gtt-orders` to implement or check GTT status.

## What GTT orders do
After the bot enters a trade, it places TWO standing orders on Kite's servers:
1. A **stop-loss order** at `signal.stop_loss` price
2. A **target order** at `signal.target` price

If the bot crashes, restarts, or loses internet — Kite's servers still execute the stop or target. Without GTT, a crash during a live trade = unlimited loss risk.

## Files to modify
- `broker/kite_broker.py` — add GTT placement after `place_order()`
- `execution/order_manager.py` — store GTT trigger IDs, cancel on manual exit
- `execution/trade_log.py` — add `gtt_trigger_id` column to trades table (if missing)

## Steps

### 1. Check current state
```bash
source venv/bin/activate
grep -n "gtt\|place_gtt\|GTT" broker/kite_broker.py execution/order_manager.py
```
If no matches → GTT is not implemented yet. Proceed with implementation.

### 2. Add GTT placement to KiteBroker
Read `broker/kite_broker.py` first, then add after a successful entry order:

```python
def place_gtt_oco(self, symbol: str, qty: int, entry_price: float,
                  stop_loss: float, target: float) -> int | None:
    """Place OCO GTT (stop + target). Returns trigger_id or None on failure."""
    try:
        trigger_id = self._kite.place_gtt(
            trigger_type=self._kite.GTT_TYPE_OCO,
            tradingsymbol=symbol,
            exchange="NSE",
            trigger_values=[stop_loss, target],
            last_price=entry_price,
            orders=[
                {
                    "transaction_type": self._kite.TRANSACTION_TYPE_SELL,
                    "quantity": qty,
                    "order_type": self._kite.ORDER_TYPE_LIMIT,
                    "product": self._kite.PRODUCT_MIS,
                    "price": stop_loss,
                },
                {
                    "transaction_type": self._kite.TRANSACTION_TYPE_SELL,
                    "quantity": qty,
                    "order_type": self._kite.ORDER_TYPE_LIMIT,
                    "product": self._kite.PRODUCT_MIS,
                    "price": target,
                },
            ],
        )
        return trigger_id
    except Exception as e:
        # Fail open — trade proceeds without GTT rather than blocking entry
        logger.error(f"GTT placement failed for {symbol}: {e}")
        return None
```

### 3. Call GTT after successful entry
In `broker/kite_broker.py` → `execute_signal()` or equivalent, after `place_order()` succeeds:
```python
gtt_id = self.place_gtt_oco(symbol, qty, fill_price, signal.stop_loss, signal.target)
if gtt_id:
    logger.info(f"GTT OCO placed for {symbol}: trigger_id={gtt_id}")
```

### 4. Store GTT trigger ID
In `execution/trade_log.py`, add `gtt_trigger_id INTEGER` column to the trades schema (migration needed):
```sql
ALTER TABLE trades ADD COLUMN gtt_trigger_id INTEGER;
```

### 5. Cancel GTT on manual/reversal exit
In `execution/order_manager.py` → `_close_trade()`:
```python
if gtt_trigger_id and hasattr(self._broker, "cancel_gtt"):
    self._broker.cancel_gtt(gtt_trigger_id)
```

Add to `KiteBroker`:
```python
def cancel_gtt(self, trigger_id: int) -> bool:
    try:
        self._kite.delete_gtt(trigger_id=trigger_id)
        return True
    except Exception as e:
        logger.warning(f"GTT cancel failed (id={trigger_id}): {e}")
        return False
```

### 6. PaperBroker stub
GTT is live-only. Add no-op stubs to `broker/paper_broker.py`:
```python
def place_gtt_oco(self, *args, **kwargs) -> None:
    return None  # Paper mode: no GTT needed

def cancel_gtt(self, trigger_id) -> bool:
    return True
```

### 7. Tests
Write tests in `tests/test_gtt_orders.py`:
- `test_gtt_placed_after_entry` — mock KiteConnect, verify `place_gtt()` called with correct prices
- `test_gtt_cancel_on_exit` — verify `delete_gtt()` called when trade closes
- `test_gtt_fail_open` — if `place_gtt()` raises, trade still recorded normally

### 8. Verify
```bash
python -m pytest tests/test_gtt_orders.py -v
```

Explain to user: "GTT is the single most important safety feature for live trading. A bot crash without GTT = your position stays open with no stop-loss. With GTT, Kite's servers protect you even if your computer is off."
