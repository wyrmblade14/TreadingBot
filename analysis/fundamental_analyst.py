"""
Fundamental Analyst — Claude AI-powered fundamental synthesis.

Why fundamentals matter for intraday trading (beginner explanation):
  Most intraday traders only look at charts and price patterns, but the company
  behind the stock also matters — even for short-term trades.

  Here's the key insight: A stock with strong fundamentals (good earnings, low
  debt, healthy margins) tends to get bought on dips and holds its levels better
  than a fundamentally weak stock. Institutions — the big mutual funds and FIIs
  that move NIFTY50 stocks — are constantly aware of fundamentals when deciding
  how aggressively to buy or sell.

  Think of it this way:
    - A fundamentally STRONG stock at a technical support level = institutions
      will likely defend that level. Your BUY signal has extra backing.
    - A fundamentally WEAK stock bouncing into resistance = institutions may
      be waiting to sell. Your BUY signal faces a headwind.

  This module does NOT override your strategy or risk rules. It adjusts
  position_scale (0.3 to 1.0) — meaning you trade a smaller or fuller
  quantity depending on how fundamentally supportive the backdrop is.

  Example:
    Normal position: ₹1,000 risk, 10 shares
    With position_scale=0.5: ₹500 risk, 5 shares
    With position_scale=1.0: ₹1,000 risk, 10 shares (full size)

How it works:
  1. You pass in raw fundamental metrics (P/E, debt/equity, margins, earnings
     growth) — these come from yfinance's `.info` dictionary.
  2. If ANTHROPIC_API_KEY is set in your .env, the Claude API reads those numbers
     and returns a structured BULLISH/BEARISH/NEUTRAL judgment with explanations.
  3. If the API key is not set (or the API call fails), a simple rule-based
     fallback kicks in — no crashes, no blocked trades.
  4. Results are cached for 24 hours per symbol. Fundamentals don't change
     minute-to-minute, so fetching them once per day is exactly right.

Cache: 24-hour TTL per symbol (fundamentals update quarterly at most).
Source: Claude API (claude-haiku-4-5) with rule-based fallback.
"""

from __future__ import annotations

import json
import os
import time as _time
from dataclasses import dataclass, field
from typing import Literal

from loguru import logger


# ── Cache (module-level, 24-hour TTL) ────────────────────────────────────────

_CACHE_TTL = 86400   # 24 hours in seconds
_judgment_cache: dict[str, tuple["FundamentalJudgment", float]] = {}


# ── Output contract ───────────────────────────────────────────────────────────

@dataclass
class FundamentalJudgment:
    """
    The structured output from a fundamental analysis.

    Fields (plain English):
        bias:           BULLISH = company is in good shape and worth full size.
                        BEARISH = company has problems; trade smaller or skip.
                        NEUTRAL = mixed picture; use a moderate position size.

        confidence:     0.0 = the analyst is guessing. 1.0 = very high confidence.
                        The rule-based fallback always returns 0.5 (medium confidence)
                        because it's a simplified heuristic.

        position_scale: How much of your normal position size to use.
                        1.0 = full position. 0.5 = half. 0.3 = minimal.
                        Your RiskManager calculates quantity first, then this
                        multiplier scales it down if fundamentals are weak.

        key_strengths:  2–4 bullet points explaining what's good about this company.
        key_risks:      2–4 bullet points explaining what's concerning.
        summary:        1–2 sentence takeaway for a quick read on the dashboard.
        source:         Where this judgment came from:
                          "claude_api"  → Claude AI analyzed the metrics
                          "rule_based"  → Simple formula (no API key / API failed)
                          "cache"       → Returned from today's earlier fetch
    """
    bias:           Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence:     float           # 0.0–1.0
    position_scale: float           # 0.3–1.0
    key_strengths:  list[str] = field(default_factory=list)   # 2–4 bullet points
    key_risks:      list[str] = field(default_factory=list)   # 2–4 bullet points
    summary:        str  = ""       # 1–2 sentences for dashboard display
    source:         str  = "rule_based"   # "claude_api" | "rule_based" | "cache"


# ── Analyst class ─────────────────────────────────────────────────────────────

class FundamentalAnalyst:
    """
    Analyzes fundamental metrics for a NIFTY50 stock and returns a structured
    trading judgment.

    Usage:
        from analysis.fundamental_analyst import analyst

        metrics = {
            "trailingPE": 18.5,
            "debtToEquity": 42.0,
            "profitMargins": 0.18,
            "earningsQuarterlyGrowth": 0.12,
        }
        judgment = analyst.analyze("RELIANCE", metrics)
        print(judgment.bias, judgment.position_scale)

    The metrics dict should come from yfinance's Ticker().info dictionary.
    Any missing keys (None values) are handled gracefully — the analyst works
    with whatever subset of data you provide.
    """

    def analyze(self, symbol: str, metrics: dict) -> FundamentalJudgment:
        """
        Analyze fundamental metrics for a stock and return a judgment.

        Uses Claude API if ANTHROPIC_API_KEY is set in .env, else falls back
        to rule-based logic. Result is cached 24 hours per symbol so the same
        stock is not re-analyzed on every signal during a trading day.

        Args:
            symbol:  NSE symbol, e.g. "RELIANCE" (Kite format, no .NS suffix).
            metrics: Dict of fundamental metrics, typically from yfinance .info.
                     Recognised keys: trailingPE, debtToEquity, profitMargins,
                     earningsQuarterlyGrowth, returnOnEquity, currentRatio,
                     revenueGrowth, grossMargins.

        Returns:
            FundamentalJudgment with bias, confidence, position_scale, and
            human-readable strengths/risks/summary.

        Never raises — always returns a safe default on unexpected errors.
        """
        try:
            now = _time.monotonic()

            # 1. Cache hit — return today's earlier result
            if symbol in _judgment_cache:
                cached_judgment, cached_ts = _judgment_cache[symbol]
                if now - cached_ts < _CACHE_TTL:
                    # Return a copy with source="cache" so callers can tell it's cached
                    return FundamentalJudgment(
                        bias=cached_judgment.bias,
                        confidence=cached_judgment.confidence,
                        position_scale=cached_judgment.position_scale,
                        key_strengths=cached_judgment.key_strengths,
                        key_risks=cached_judgment.key_risks,
                        summary=cached_judgment.summary,
                        source="cache",
                    )

            # 2. Try Claude API first (only if API key is set)
            api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
            judgment: FundamentalJudgment | None = None

            if api_key:
                try:
                    judgment = self._call_claude(symbol, metrics)
                except Exception as exc:
                    logger.warning(
                        f"FundamentalAnalyst: Claude API failed for {symbol}: {exc}"
                    )

            # 3. Fallback to rule-based if API not available or call failed
            if judgment is None:
                judgment = self._rule_based(symbol, metrics)

            # 4. Cache and return
            _judgment_cache[symbol] = (judgment, now)
            logger.debug(
                f"FundamentalAnalyst: {symbol} → {judgment.bias} "
                f"(scale={judgment.position_scale:.1f}, source={judgment.source})"
            )
            return judgment

        except Exception as exc:
            # Safety net — fundamental analysis must NEVER block a trade
            logger.error(f"FundamentalAnalyst: unexpected error for {symbol}: {exc}")
            return FundamentalJudgment(
                bias="NEUTRAL",
                confidence=0.0,
                position_scale=1.0,
                key_strengths=[],
                key_risks=[],
                summary="Analysis unavailable.",
                source="rule_based",
            )

    # ── Claude API path ───────────────────────────────────────────────────────

    def _call_claude(self, symbol: str, metrics: dict) -> FundamentalJudgment:
        """
        Call Claude API (claude-haiku-4-5) with a structured prompt and parse
        the JSON response into a FundamentalJudgment.

        Raises on any API or parsing error (caller wraps in try/except).
        """
        import anthropic

        client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from env

        # Filter out None values so the prompt stays concise
        clean_metrics = {k: v for k, v in metrics.items() if v is not None}

        prompt = f"""You are analyzing fundamental data for {symbol}, an Indian stock on the NSE NIFTY50 index.

Fundamental metrics:
{json.dumps(clean_metrics, indent=2)}

Based on these metrics, provide a fundamental analysis judgment for SHORT-TERM INTRADAY TRADING (not long-term investing).

Respond with ONLY valid JSON matching this exact schema:
{{
  "bias": "BULLISH" | "BEARISH" | "NEUTRAL",
  "confidence": 0.0-1.0,
  "position_scale": 0.3-1.0,
  "key_strengths": ["strength1", "strength2"],
  "key_risks": ["risk1", "risk2"],
  "summary": "1-2 sentence summary for an intraday trader"
}}

Guidelines:
- BULLISH: fundamentally strong company, below-sector P/E, growing earnings → full position scale 1.0
- BEARISH: deteriorating earnings, over-leveraged, or extreme valuation → reduced scale 0.3
- NEUTRAL: mixed signals → scale 0.6
- For intraday trading, earnings blackout risk and earnings trend matter most
- Keep key_strengths and key_risks to 2-3 items each, in plain English"""

        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text.strip()

        # Strip markdown code fences if Claude wraps the JSON in ```json ... ```
        if response_text.startswith("```"):
            parts = response_text.split("```")
            # parts[1] is the content inside the first fence pair
            inner = parts[1] if len(parts) > 1 else response_text
            if inner.startswith("json"):
                inner = inner[4:]
            response_text = inner.strip()

        data = json.loads(response_text)

        return FundamentalJudgment(
            bias=data["bias"],
            confidence=float(data["confidence"]),
            position_scale=float(data["position_scale"]),
            key_strengths=data.get("key_strengths", []),
            key_risks=data.get("key_risks", []),
            summary=data.get("summary", ""),
            source="claude_api",
        )

    # ── Rule-based fallback ───────────────────────────────────────────────────

    def _rule_based(self, symbol: str, metrics: dict) -> FundamentalJudgment:
        """
        Simple rule-based judgment without AI.

        Used as fallback when:
          - ANTHROPIC_API_KEY is not set in .env
          - The Claude API call fails for any reason

        Logic (each metric independently contributes a bullish or bearish signal):
          P/E < 20              → bullish (stock not overpriced)
          P/E > 60              → bearish (priced for perfection; risk of correction)
          Debt/Equity < 30      → bullish (low leverage, strong balance sheet)
          Debt/Equity > 100     → bearish (high debt = fragile in downturns)
          Profit margins > 15%  → bullish (efficient, keeps more of each rupee earned)
          Profit margins < 5%   → bearish (thin margins = vulnerable to cost shocks)
          Quarterly EPS growth > 5%  → bullish (earnings accelerating)
          Quarterly EPS growth < -5% → bearish (earnings deteriorating)

        Final judgment:
          2+ bearish signals → BEARISH, scale 0.3
          2+ bullish signals → BULLISH, scale 1.0
          Otherwise          → NEUTRAL,  scale 0.6
        """
        strengths: list[str] = []
        risks:     list[str] = []
        bullish_signals = 0
        bearish_signals = 0

        pe     = metrics.get("trailingPE")
        debt   = metrics.get("debtToEquity")
        margins = metrics.get("profitMargins")
        growth = metrics.get("earningsQuarterlyGrowth")

        # ── P/E ratio ─────────────────────────────────────────────────────────
        # P/E = Price ÷ Earnings per share.
        # A low P/E means you're paying less for every rupee the company earns.
        # A very high P/E means the stock is priced for high future growth —
        # any disappointment can cause a sharp drop.
        if pe is not None:
            if pe < 20:
                bullish_signals += 1
                strengths.append(f"Low P/E of {pe:.1f} — attractively valued")
            elif pe > 60:
                bearish_signals += 1
                risks.append(f"High P/E of {pe:.1f} — priced for perfection")

        # ── Debt / Equity ─────────────────────────────────────────────────────
        # Debt/Equity tells you how much the company borrowed vs. shareholder
        # funds. Low debt = the company does not depend heavily on borrowed
        # money, so it can weather slowdowns. High debt = interest payments
        # eat into profits and make the stock volatile.
        if debt is not None:
            if debt < 30:
                bullish_signals += 1
                strengths.append(f"Low debt/equity {debt:.1f} — strong balance sheet")
            elif debt > 100:
                bearish_signals += 1
                risks.append(f"High debt/equity {debt:.1f} — leveraged balance sheet")

        # ── Profit margins ────────────────────────────────────────────────────
        # Profit margin = Net profit ÷ Revenue.
        # A 15%+ margin means the company keeps ₹15 or more from every ₹100
        # it earns. This is a sign of pricing power and operational efficiency.
        # Thin margins (< 5%) mean a small revenue dip can wipe out all profit.
        if margins is not None:
            if margins > 0.15:
                bullish_signals += 1
                strengths.append(f"Strong profit margin {margins:.0%}")
            elif margins < 0.05:
                bearish_signals += 1
                risks.append(f"Thin profit margin {margins:.0%}")

        # ── Earnings growth (quarter-over-quarter) ────────────────────────────
        # This shows whether the company is earning more or less than it did
        # last quarter. Growing earnings → institutions buy more. Shrinking
        # earnings → institutions reduce positions.
        if growth is not None:
            if growth > 0.05:
                bullish_signals += 1
                strengths.append(f"Earnings growing {growth:.0%} QoQ")
            elif growth < -0.05:
                bearish_signals += 1
                risks.append(f"Earnings shrinking {growth:.0%} QoQ")

        # ── Final judgment ────────────────────────────────────────────────────
        if bearish_signals >= 2:
            bias  = "BEARISH"
            scale = 0.3
        elif bullish_signals >= 2:
            bias  = "BULLISH"
            scale = 1.0
        else:
            bias  = "NEUTRAL"
            scale = 0.6

        return FundamentalJudgment(
            bias=bias,
            confidence=0.5,   # rule-based is always medium confidence
            position_scale=scale,
            key_strengths=strengths or ["No significant strengths identified"],
            key_risks=risks     or ["No significant risks identified"],
            summary=f"Rule-based assessment: {bias.lower()} fundamentals for {symbol}.",
            source="rule_based",
        )


# ── Module-level singleton ────────────────────────────────────────────────────
# Import this wherever you need fundamental analysis:
#   from analysis.fundamental_analyst import analyst
#   judgment = analyst.analyze("RELIANCE", metrics)

analyst = FundamentalAnalyst()
