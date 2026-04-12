"""
Lightweight JSON API for the Next.js dashboard.

The React dashboard needs live project data, but the trading runtime should not
gain another Python web framework just for read-only dashboard endpoints. This
module intentionally uses only the standard library plus existing project code.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TRADE_LIMIT = 200
MAX_TRADE_LIMIT = 2000

LOCAL_NEXT_ORIGINS = {
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
}


def _load_env() -> None:
    """Load repo-root .env before importing modules that read env at import time."""
    env_path = ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
        return
    except Exception:
        pass

    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass


_load_env()


def _safe_error(exc: BaseException | str) -> str:
    message = str(exc)
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        message = message.replace(db_url, "[DATABASE_URL]")
    if message:
        return message
    return exc.__class__.__name__ if isinstance(exc, BaseException) else ""


def _json_safe(value: Any) -> Any:
    """Convert common project/Python data types into JSON-native values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, Decimal):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _json_safe(dataclasses.asdict(value))

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except Exception:
            pass

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _json_safe(to_dict())
        except Exception:
            pass

    return str(value)


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(_json_safe(payload), separators=(",", ":")).encode("utf-8")


def _configured_capital() -> float:
    try:
        from config.settings import VIRTUAL_CAPITAL

        return float(VIRTUAL_CAPITAL)
    except Exception:
        return 100000.0


def _empty_trade_data(error: str | None = None) -> dict[str, Any]:
    capital = _configured_capital()
    return {
        "capital": capital,
        "initialCapital": capital,
        "todayPnl": 0.0,
        "totalPnl": 0.0,
        "totalReturnPct": 0.0,
        "tradeCountToday": 0,
        "tradingDays": 0,
        "closedTrades": 0,
        "wins": 0,
        "losses": 0,
        "winRatePct": 0.0,
        "todayTrades": [],
        "dailyPnl": [],
        "recentTrades": [],
        "strategySummary": [],
        "error": error,
    }


def _parse_limit(query: dict[str, list[str]]) -> tuple[int, str | None]:
    raw_limit = query.get("limit", [str(DEFAULT_TRADE_LIMIT)])[0]
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return DEFAULT_TRADE_LIMIT, f"Invalid limit '{raw_limit}', using {DEFAULT_TRADE_LIMIT}."

    if limit < 1:
        return DEFAULT_TRADE_LIMIT, f"Limit must be positive, using {DEFAULT_TRADE_LIMIT}."
    if limit > MAX_TRADE_LIMIT:
        return MAX_TRADE_LIMIT, f"Limit capped at {MAX_TRADE_LIMIT}."
    return limit, None


def _safe_trade_data(limit: int = 500) -> tuple[dict[str, Any], str | None]:
    if not os.environ.get("DATABASE_URL"):
        error = "DATABASE_URL is not set; trade data is unavailable."
        return _empty_trade_data(error), error

    try:
        from execution.trade_log import TradeLogger

        trade_log = TradeLogger()
        today_trades = trade_log.get_today_trades()
        daily_pnl = trade_log.get_daily_pnl()
        all_trades = trade_log.get_all_trades(limit=limit)
        strategy_summary = trade_log.get_strategy_summary()
    except Exception as exc:
        error = _safe_error(exc)
        return _empty_trade_data(error), error

    initial_capital = _configured_capital()
    total_pnl = sum(float(row.get("net_pnl") or 0) for row in daily_pnl)
    today_key = date.today().isoformat()
    today_pnl = next(
        (float(row.get("net_pnl") or 0) for row in daily_pnl if row.get("date") == today_key),
        0.0,
    )

    closed = [trade for trade in all_trades if trade.get("net_pnl") is not None]
    wins = [trade for trade in closed if float(trade.get("net_pnl") or 0) > 0]
    losses = [trade for trade in closed if float(trade.get("net_pnl") or 0) < 0]

    return {
        "capital": initial_capital + total_pnl,
        "initialCapital": initial_capital,
        "todayPnl": today_pnl,
        "totalPnl": total_pnl,
        "totalReturnPct": (total_pnl / initial_capital * 100) if initial_capital else 0.0,
        "tradeCountToday": len(today_trades),
        "tradingDays": len(daily_pnl),
        "closedTrades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winRatePct": (len(wins) / len(closed) * 100) if closed else 0.0,
        "todayTrades": today_trades,
        "dailyPnl": list(reversed(daily_pnl)),
        "recentTrades": all_trades,
        "strategySummary": strategy_summary,
        "error": None,
    }, None


def _safe_bot_status() -> tuple[dict[str, Any], str | None]:
    try:
        from scheduler.bot_controller import get_controller

        status = get_controller().get_status()
        return status, None
    except Exception as exc:
        error = _safe_error(exc)
        return {
            "status": "unknown",
            "started_at": None,
            "watchlist_size": 0,
            "capital": 0,
            "pid": None,
            "owned_by_ui": False,
            "next_jobs": [],
            "error": error,
        }, error


def _empty_market_overview(error: str | None = None) -> dict[str, Any]:
    return {
        "nifty_price": None,
        "nifty_change": None,
        "nifty_change_pct": None,
        "advances": 0,
        "declines": 0,
        "unchanged": 0,
        "top_gainers": [],
        "top_losers": [],
        "total_symbols": 0,
        "error": error,
    }


def _safe_market_overview() -> tuple[dict[str, Any], str | None]:
    try:
        from analysis.market_overview import get_nifty_overview

        overview = get_nifty_overview(top_n=5)
    except Exception as exc:
        error = _safe_error(exc)
        return _empty_market_overview(error), error

    if overview is None:
        error = "Market overview data is unavailable."
        return _empty_market_overview(error), error

    data = _json_safe(overview)
    if not isinstance(data, dict):
        data = {"value": data}
    data["error"] = None
    return data, None


def _health_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "treadingbot-dashboard-api",
        "timestamp": datetime.now().isoformat(),
        "databaseConfigured": bool(os.environ.get("DATABASE_URL")),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TreadingBotDashboardAPI/1.0"

    def do_OPTIONS(self) -> None:
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except Exception as exc:
            self._send_json({"error": _safe_error(exc)}, status=500)

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self._send_json(_health_payload())
            return

        if path == "/api/dashboard":
            trades, trade_error = _safe_trade_data(limit=500)
            bot, bot_error = _safe_bot_status()
            market, market_error = _safe_market_overview()
            self._send_json({
                "trades": trades,
                "bot": bot,
                "market": market,
                "errors": [err for err in (trade_error, bot_error, market_error) if err],
            })
            return

        if path == "/api/trades":
            limit, limit_error = _parse_limit(query)
            trades, trade_error = _safe_trade_data(limit=limit)
            self._send_json({
                "items": trades["recentTrades"][:limit],
                "limit": limit,
                "error": trade_error or limit_error,
            })
            return

        if path == "/api/bot/status":
            status, error = _safe_bot_status()
            self._send_json({"status": status, "error": error})
            return

        if path == "/api/market/overview":
            overview, error = _safe_market_overview()
            self._send_json({"overview": overview, "error": error})
            return

        self._send_json({"error": "not found"}, status=404)

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = _json_bytes(payload)
        origin = self.headers.get("Origin")
        allowed_origin = origin if origin in LOCAL_NEXT_ORIGINS else "*"

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", allowed_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"TreadingBot dashboard API running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTreadingBot dashboard API stopped.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the TreadingBot dashboard JSON API.")
    parser.add_argument("--host", default=os.environ.get("DASHBOARD_API_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DASHBOARD_API_PORT", DEFAULT_PORT)),
    )
    args = parser.parse_args(argv)
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
