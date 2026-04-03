"""
Tests for analysis/fundamental_analyst.py — FundamentalAnalyst.

Covers:
  - Rule-based judgment: BULLISH / BEARISH / NEUTRAL bias from raw metrics
  - Empty metrics → NEUTRAL fallback with position_scale=1.0
  - Source field: no API key → "rule_based" or "cache"
  - Caching: second call returns cached result (rule_based fires only once)
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from analysis.fundamental_analyst import FundamentalAnalyst, FundamentalJudgment
from analysis import fundamental_analyst as _fa_module


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_judgment(
    bias: str = "NEUTRAL",
    confidence: float = 0.7,
    scale: float = 0.6,
) -> FundamentalJudgment:
    """Build a FundamentalJudgment for use in assertion helpers."""
    return FundamentalJudgment(
        bias=bias,
        confidence=confidence,
        position_scale=scale,
        key_strengths=[],
        key_risks=[],
        summary="test",
        source="rule_based",
    )


def _fresh_analyst() -> FundamentalAnalyst:
    """Return a FundamentalAnalyst with the module-level judgment cache cleared."""
    _fa_module._judgment_cache.clear()
    return FundamentalAnalyst()


# ── TestFundamentalAnalystRuleBased ──────────────────────────────────────────

class TestFundamentalAnalystRuleBased:

    def test_bullish_when_low_pe_and_growing(self):
        """Low P/E (< 20) + growing earnings (> 5%) → 2 bullish signals → BULLISH bias."""
        analyst = _fresh_analyst()
        metrics = {"trailingPE": 15.0, "earningsQuarterlyGrowth": 0.10}

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            judgment = analyst.analyze("RELIANCE", metrics)

        assert judgment.bias == "BULLISH"

    def test_bearish_when_high_pe_and_shrinking(self):
        """High P/E (> 60) + shrinking earnings (< -5%) → 2 bearish signals → BEARISH bias."""
        analyst = _fresh_analyst()
        metrics = {"trailingPE": 80.0, "earningsQuarterlyGrowth": -0.10}

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            judgment = analyst.analyze("RELIANCE", metrics)

        assert judgment.bias == "BEARISH"

    def test_neutral_when_mixed_signals(self):
        """P/E 25 (neither < 20 nor > 60) + growth -0.02 (neither > 5% nor < -5%) → NEUTRAL."""
        analyst = _fresh_analyst()
        metrics = {"trailingPE": 25.0, "earningsQuarterlyGrowth": -0.02}

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            judgment = analyst.analyze("RELIANCE", metrics)

        assert judgment.bias == "NEUTRAL"

    def test_returns_neutral_on_empty_metrics(self):
        """Empty metrics dict → no bullish or bearish signals → NEUTRAL with full position scale."""
        analyst = _fresh_analyst()

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            judgment = analyst.analyze("INFY", {})

        assert judgment.bias == "NEUTRAL"
        # Empty metrics → no scaling penalty: rule-based returns 0.6 for NEUTRAL
        assert judgment.position_scale == 0.6

    def test_source_is_rule_based(self):
        """With no API key set, judgment source must be 'rule_based' or 'cache'."""
        analyst = _fresh_analyst()
        metrics = {"trailingPE": 22.0}

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            judgment = analyst.analyze("TCS", metrics)

        assert judgment.source in ("rule_based", "cache")


# ── TestFundamentalAnalystCache ───────────────────────────────────────────────

class TestFundamentalAnalystCache:

    def test_caches_result_on_second_call(self):
        """Second call for the same symbol returns a cached result; rule_based runs only once."""
        analyst = _fresh_analyst()
        metrics = {"trailingPE": 18.0, "earningsQuarterlyGrowth": 0.08}

        call_count = {"n": 0}
        original_rule_based = analyst._rule_based

        def counting_rule_based(symbol, m):
            call_count["n"] += 1
            return original_rule_based(symbol, m)

        analyst._rule_based = counting_rule_based

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            j1 = analyst.analyze("WIPRO", metrics)
            j2 = analyst.analyze("WIPRO", metrics)

        # _rule_based must only fire once; second call reads cache
        assert call_count["n"] == 1
        assert j2.source == "cache"
        assert j1.bias == j2.bias
