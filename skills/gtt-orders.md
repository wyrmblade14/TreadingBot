# Skill: gtt-orders
**Role:** GTT Orders Implementation Expert  
**Trigger:** user asks about GTT, crash-safe stops, live order safety, or types `gtt-orders`

GTT (Good Till Triggered) = OCO stop+target orders placed on Kite's servers that survive bot crashes.
This implements idea #6 from `memory/ideas_and_improvements.md`.

## What GTT Does
After entry, two standing orders live on Kite's servers:
1. **Stop-loss order** at `signal.stop_loss`
2. **Target order** at `signal.target`

If the bot crashes, restarts, or loses internet — Kite still executes the stop or target.
Without GTT: crash during a live trade = unlimited loss risk.

## Files to Modify
- `broker/kite_broker.py` — add GTT placement after `place_order()`
- `execution/order_manager.py` — store GTT IDs, cancel on manual exit
- `execution/trade_log.py` — add `gtt_trigger_id INTEGER` column

## Implementation Steps

### 1. Check current state
```bash
source venv/bin/activate
grep -n "gtt\|place_gtt\|GTT" broker/kite_broker.py execution/order_manager.py
```
No matches = GTT not yet implemented.

### 2. Add `place_gtt_oco()` to KiteBroker
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
                {"transaction_type": self._kite.TRANSACTION_TYPE_SELL,
                 "quantity": qty, "order_type": self._kite.ORDER_TYPE_LIMIT,
                 "product": self._kite.PRODUCT_MIS, "price": stop_loss},
                {"transaction_type": self._kite.TRANSACTION_TYPE_SELL,
                 "quantity": qty, "order_type": self._kite.ORDER_TYPE_LIMIT,
                 "product": self._kite.PRODUCT_MIS, "price": target},
            ],
        )
        return trigger_id
    except Exception as e:
        logger.error(f"GTT placement failed for {symbol}: {e}")
        return None  # Fail open — trade proceeds without GTT
```

### 3. Call GTT after successful entry
In `execute_signal()` after `place_order()` succeeds:
```python
gtt_id = self.place_gtt_oco(symbol, qty, fill_price, signal.stop_loss, signal.target)
if gtt_id:
    logger.info(f"GTT OCO placed for {symbol}: trigger_id={gtt_id}")
```

### 4. Add `gtt_trigger_id` to DB
```sql
ALTER TABLE trades ADD COLUMN gtt_trigger_id INTEGER;
```
Add to `TradeLogger` schema if column missing.

### 5. Cancel GTT on manual/reversal exit
In `order_manager.py` → `_close_trade()`:
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

### 6. PaperBroker stubs (no-op)
```python
def place_gtt_oco(self, *args, **kwargs) -> None:
    return None

def cancel_gtt(self, trigger_id) -> bool:
    return True
```

### 7. Tests
Write `tests/test_gtt_orders.py`:
- `test_gtt_placed_after_entry` — mock KiteConnect, verify `place_gtt()` called with correct prices
- `test_gtt_cancel_on_exit` — verify `delete_gtt()` called when trade closes
- `test_gtt_fail_open` — if `place_gtt()` raises, trade still recorded normally

```bash
python -m pytest tests/test_gtt_orders.py -v
```

**Explain to beginner:** "GTT is the single most important safety feature for live trading. A bot crash without GTT leaves your position open with no protection. With GTT, Kite's servers protect you even if your computer is off."
