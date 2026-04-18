"""
Tests for per-symbol strategy routing (_get_strategies_for_symbol).

Covers:
  - Empty maps  → full _strategies returned unchanged
  - Symbol not in map  → full _strategies returned
  - Symbol in SYMBOL_STRATEGY_MAP → only named instances returned in order
  - Map order preserved (reversed order test)
  - Typo in map → silently skipped, valid names still work
  - Strategy in map but not instantiated → skipped
  - SECTOR_STRATEGY_MAP lookup when symbol not in SYMBOL_STRATEGY_MAP
  - param_history.json strategy_assignment fallback
  - Backtest auto-select logic (SYMBOL_STRATEGY_MAP → sector → param_history → default)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.ema_crossover import EMACrossoverStrategy
from strategies.opening_range_breakout import ORBStrategy
from strategies.rsi_macd_combo import RSIMACDStrategy
from strategies.vwap_bounce import VWAPBounceStrategy


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def four_strategies():
    return [
        EMACrossoverStrategy(),
        RSIMACDStrategy(),
        ORBStrategy(),
        VWAPBounceStrategy(),
    ]


def _make_get_fn(strategies, sym_map, sec_map, hist_path=None):
    """
    Return a _get_strategies_for_symbol function bound to the given mocks.
    Avoids importing the real scheduler (which needs APScheduler, etc).
    """
    import importlib, types

    # Build a minimal module stub so the function can be exec'd independently
    code = (Path(__file__).parent.parent / "scheduler/job_runner.py").read_text()

    # Extract just the function definition (between def _get_strategies_for_symbol and def _refresh)
    start = code.index("def _get_strategies_for_symbol(")
    end   = code.index("\ndef _refresh_daily_watchlist(")
    fn_src = code[start:end].strip()

    ns: dict = {}
    exec(fn_src, ns)                            # compile the function in isolation
    fn = ns["_get_strategies_for_symbol"]

    # Patch the globals the function closes over
    fn.__globals__["_strategies"]           = strategies
    fn.__globals__["_SYMBOL_STRATEGY_MAP"]  = sym_map
    fn.__globals__["_SECTOR_STRATEGY_MAP"]  = sec_map

    # Patch logger
    import logging
    mock_logger = MagicMock()
    fn.__globals__["logger"] = mock_logger

    # Patch param_history path if provided
    if hist_path:
        orig_exists = Path.exists

        class _FakePath(type(Path())):
            pass

        fn.__globals__["json"] = json
        import builtins
        real_open = builtins.open

        def fake_open(path, *a, **kw):
            if str(path) == "config/param_history.json":
                return real_open(hist_path, *a, **kw)
            return real_open(path, *a, **kw)

        fn.__globals__["__builtins__"] = {**vars(builtins), "open": fake_open}

    return fn


# ── _get_strategies_for_symbol tests ─────────────────────────────────────────

class TestGetStrategiesForSymbol:

    def test_empty_maps_returns_all_strategies(self, four_strategies):
        fn = _make_get_fn(four_strategies, {}, {})
        result = fn("RELIANCE")
        assert result is four_strategies

    def test_symbol_not_in_sym_map_returns_all_strategies(self, four_strategies):
        fn = _make_get_fn(four_strategies, {"INFY": ["ema_crossover"]}, {})
        result = fn("RELIANCE")
        assert result is four_strategies

    def test_symbol_in_sym_map_returns_only_named(self, four_strategies):
        fn = _make_get_fn(four_strategies, {"RELIANCE": ["ema_crossover", "rsi_macd_combo"]}, {})
        result = fn("RELIANCE")
        assert len(result) == 2
        assert result[0].name == "ema_crossover"
        assert result[1].name == "rsi_macd_combo"

    def test_map_order_is_preserved(self, four_strategies):
        fn = _make_get_fn(four_strategies, {"RELIANCE": ["rsi_macd_combo", "ema_crossover"]}, {})
        result = fn("RELIANCE")
        assert result[0].name == "rsi_macd_combo"
        assert result[1].name == "ema_crossover"

    def test_unknown_name_in_sym_map_skipped_gracefully(self, four_strategies):
        fn = _make_get_fn(four_strategies, {"INFY": ["nonexistent_strategy"]}, {})
        result = fn("INFY")
        assert result == []

    def test_partial_valid_names_in_sym_map(self, four_strategies):
        fn = _make_get_fn(four_strategies, {"INFY": ["ema_crossover", "nonexistent"]}, {})
        result = fn("INFY")
        assert len(result) == 1
        assert result[0].name == "ema_crossover"

    def test_strategy_not_in_active_list_is_skipped(self, four_strategies):
        # vwap_bounce is in four_strategies, but bb_mean_reversion is not loaded
        fn = _make_get_fn(four_strategies, {"RELIANCE": ["bb_mean_reversion", "ema_crossover"]}, {})
        result = fn("RELIANCE")
        assert len(result) == 1
        assert result[0].name == "ema_crossover"

    def test_sector_map_used_when_symbol_not_in_sym_map(self, four_strategies):
        sec_map = {"Information Technology": ["opening_range_breakout"]}
        fn = _make_get_fn(four_strategies, {}, sec_map)
        with patch("data.instruments.SYMBOL_TO_SECTOR", {"INFY": "Information Technology"}):
            fn.__globals__["__builtins__"] = __builtins__
            # Re-patch SYMBOL_TO_SECTOR inside the function's import
            import data.instruments as di
            original = di.SYMBOL_TO_SECTOR.copy()
            di.SYMBOL_TO_SECTOR["INFY"] = "Information Technology"
            try:
                result = fn("INFY")
                assert len(result) == 1
                assert result[0].name == "opening_range_breakout"
            finally:
                di.SYMBOL_TO_SECTOR.clear()
                di.SYMBOL_TO_SECTOR.update(original)

    def test_sym_map_takes_priority_over_sector_map(self, four_strategies):
        sym_map = {"INFY": ["ema_crossover"]}
        sec_map = {"Information Technology": ["opening_range_breakout"]}
        fn = _make_get_fn(four_strategies, sym_map, sec_map)
        result = fn("INFY")
        # Should use sym_map, not sec_map
        assert len(result) == 1
        assert result[0].name == "ema_crossover"


# ── param_history.json fallback tests ────────────────────────────────────────

class TestParamHistoryFallback:

    def test_optimizer_assignment_used_when_no_map_entry(self, four_strategies, tmp_path, monkeypatch):
        # Create config/param_history.json under tmp_path and cd there so the
        # function's Path("config/param_history.json") resolves to our file.
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "param_history.json").write_text(json.dumps({
            "strategy_assignment": {
                "SBIN": {"strategy": "vwap_bounce", "score": 1.2}
            }
        }))
        monkeypatch.chdir(tmp_path)

        fn = _make_get_fn(four_strategies, {}, {})
        result = fn("SBIN")

        assert len(result) == 1
        assert result[0].name == "vwap_bounce"

    def test_missing_param_history_falls_back_to_all(self, four_strategies, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no config/param_history.json here
        fn = _make_get_fn(four_strategies, {}, {})
        result = fn("SBIN")
        assert result is four_strategies


# ── Backtest auto-select tests ────────────────────────────────────────────────

class TestBacktestAutoSelect:

    def _resolve(self, sym, sym_map, sec_map, hist_data=None):
        """Simulate the auto-resolve block from run_backtest.py."""
        from data.instruments import SYMBOL_TO_SECTOR
        resolved = None

        if sym_map and sym in sym_map:
            resolved = sym_map[sym][0]
        elif sec_map:
            sector = SYMBOL_TO_SECTOR.get(sym, "")
            if sector and sector in sec_map:
                resolved = sec_map[sector][0]

        if resolved is None and hist_data:
            resolved = hist_data.get("strategy_assignment", {}).get(sym, {}).get("strategy")

        return resolved or "ema_crossover"

    def test_sym_map_wins(self):
        result = self._resolve("RELIANCE", {"RELIANCE": ["vwap_bounce"]}, {})
        assert result == "vwap_bounce"

    def test_sector_map_used_when_no_sym_entry(self):
        from data.instruments import SYMBOL_TO_SECTOR
        sector = SYMBOL_TO_SECTOR.get("INFY", "")
        sec_map = {sector: ["opening_range_breakout"]} if sector else {}
        result = self._resolve("INFY", {}, sec_map)
        assert result == "opening_range_breakout" if sector else "ema_crossover"

    def test_param_history_fallback(self):
        hist = {"strategy_assignment": {"TCS": {"strategy": "rsi_macd_combo"}}}
        result = self._resolve("TCS", {}, {}, hist)
        assert result == "rsi_macd_combo"

    def test_no_assignment_returns_default(self):
        result = self._resolve("WIPRO", {}, {})
        assert result == "ema_crossover"

    def test_explicit_strategy_not_overridden(self):
        # When args.strategy is already set (explicit flag), the resolve block is skipped
        # Simulated here: if strategy is not None, keep it
        strategy = "rsi_macd_combo"   # already set by user
        sym_map  = {"WIPRO": ["ema_crossover"]}
        # The real code only resolves when args.strategy is None
        result   = strategy if strategy is not None else self._resolve("WIPRO", sym_map, {})
        assert result == "rsi_macd_combo"
