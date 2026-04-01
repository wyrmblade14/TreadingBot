"""
NIFTY50 instruments registry.

NIFTY50 is India's flagship stock index containing the 50 largest companies
listed on NSE. These stocks are the most liquid (easiest to buy/sell quickly)
and hardest to manipulate — ideal for a beginner's trading bot.

Symbol formats:
  - Kite Connect (live trading): "RELIANCE", "INFY"  (no suffix)
  - yfinance (historical data):  "RELIANCE.NS", "INFY.NS"  (.NS = NSE)

Sectors help us understand market breadth and avoid over-concentration
in one industry.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Instrument:
    kite_symbol: str    # Symbol used with Zerodha Kite Connect API
    yf_symbol: str      # Symbol used with yfinance for historical data
    name: str           # Company name (for display)
    sector: str         # Industry sector


# Complete NIFTY50 constituents (as of early 2025)
NIFTY50_INSTRUMENTS: list[Instrument] = [
    # ── Financial Services ──────────────────────────────────────────
    Instrument("HDFCBANK",      "HDFCBANK.NS",      "HDFC Bank",                "Financial Services"),
    Instrument("ICICIBANK",     "ICICIBANK.NS",     "ICICI Bank",               "Financial Services"),
    Instrument("KOTAKBANK",     "KOTAKBANK.NS",     "Kotak Mahindra Bank",      "Financial Services"),
    Instrument("AXISBANK",      "AXISBANK.NS",      "Axis Bank",                "Financial Services"),
    Instrument("SBIN",          "SBIN.NS",          "State Bank of India",      "Financial Services"),
    Instrument("BAJFINANCE",    "BAJFINANCE.NS",    "Bajaj Finance",            "Financial Services"),
    Instrument("BAJAJFINSV",    "BAJAJFINSV.NS",    "Bajaj Finserv",            "Financial Services"),
    Instrument("SHRIRAMFIN",    "SHRIRAMFIN.NS",    "Shriram Finance",          "Financial Services"),

    # ── Information Technology ──────────────────────────────────────
    Instrument("TCS",           "TCS.NS",           "Tata Consultancy Services","Information Technology"),
    Instrument("INFY",          "INFY.NS",          "Infosys",                  "Information Technology"),
    Instrument("HCLTECH",       "HCLTECH.NS",       "HCL Technologies",         "Information Technology"),
    Instrument("WIPRO",         "WIPRO.NS",         "Wipro",                    "Information Technology"),
    Instrument("TECHM",         "TECHM.NS",         "Tech Mahindra",            "Information Technology"),
    Instrument("LTIM",          "LTIM.NS",          "LTIMindtree",              "Information Technology"),

    # ── Oil & Gas ───────────────────────────────────────────────────
    Instrument("RELIANCE",      "RELIANCE.NS",      "Reliance Industries",      "Oil & Gas"),
    Instrument("ONGC",          "ONGC.NS",          "Oil & Natural Gas Corp",   "Oil & Gas"),
    Instrument("BPCL",          "BPCL.NS",          "Bharat Petroleum",         "Oil & Gas"),
    Instrument("IOC",           "IOC.NS",           "Indian Oil Corporation",   "Oil & Gas"),

    # ── Fast Moving Consumer Goods (FMCG) ──────────────────────────
    Instrument("HINDUNILVR",    "HINDUNILVR.NS",    "Hindustan Unilever",       "FMCG"),
    Instrument("ITC",           "ITC.NS",           "ITC Limited",              "FMCG"),
    Instrument("NESTLEIND",     "NESTLEIND.NS",     "Nestle India",             "FMCG"),
    Instrument("BRITANNIA",     "BRITANNIA.NS",     "Britannia Industries",     "FMCG"),
    Instrument("TATACONSUM",    "TATACONSUM.NS",    "Tata Consumer Products",   "FMCG"),

    # ── Automotive ──────────────────────────────────────────────────
    Instrument("MARUTI",        "MARUTI.NS",        "Maruti Suzuki",            "Automotive"),
    Instrument("TATAMOTORS",    "TATAMOTORS.NS",    "Tata Motors",              "Automotive"),
    Instrument("M&M",           "M&M.NS",           "Mahindra & Mahindra",      "Automotive"),
    Instrument("EICHERMOT",     "EICHERMOT.NS",     "Eicher Motors",            "Automotive"),
    Instrument("HEROMOTOCO",    "HEROMOTOCO.NS",    "Hero MotoCorp",            "Automotive"),
    Instrument("BAJAJ-AUTO",    "BAJAJ-AUTO.NS",    "Bajaj Auto",               "Automotive"),

    # ── Healthcare / Pharma ─────────────────────────────────────────
    Instrument("SUNPHARMA",     "SUNPHARMA.NS",     "Sun Pharmaceutical",       "Healthcare"),
    Instrument("DRREDDY",       "DRREDDY.NS",       "Dr. Reddy's Laboratories", "Healthcare"),
    Instrument("CIPLA",         "CIPLA.NS",         "Cipla",                    "Healthcare"),
    Instrument("DIVISLAB",      "DIVISLAB.NS",      "Divi's Laboratories",      "Healthcare"),
    Instrument("APOLLOHOSP",    "APOLLOHOSP.NS",    "Apollo Hospitals",         "Healthcare"),

    # ── Metals & Mining ─────────────────────────────────────────────
    Instrument("TATASTEEL",     "TATASTEEL.NS",     "Tata Steel",               "Metals"),
    Instrument("JSWSTEEL",      "JSWSTEEL.NS",      "JSW Steel",                "Metals"),
    Instrument("HINDALCO",      "HINDALCO.NS",      "Hindalco Industries",      "Metals"),
    Instrument("VEDL",          "VEDL.NS",          "Vedanta",                  "Metals"),
    Instrument("COALINDIA",     "COALINDIA.NS",     "Coal India",               "Metals"),

    # ── Conglomerates / Infrastructure ──────────────────────────────
    Instrument("LT",            "LT.NS",            "Larsen & Toubro",          "Infrastructure"),
    Instrument("ADANIENT",      "ADANIENT.NS",      "Adani Enterprises",        "Infrastructure"),
    Instrument("ADANIPORTS",    "ADANIPORTS.NS",    "Adani Ports",              "Infrastructure"),
    Instrument("POWERGRID",     "POWERGRID.NS",     "Power Grid Corporation",   "Infrastructure"),
    Instrument("NTPC",          "NTPC.NS",          "NTPC Limited",             "Infrastructure"),

    # ── Telecom ─────────────────────────────────────────────────────
    Instrument("BHARTIARTL",    "BHARTIARTL.NS",    "Bharti Airtel",            "Telecom"),

    # ── Cement ──────────────────────────────────────────────────────
    Instrument("ULTRACEMCO",    "ULTRACEMCO.NS",    "UltraTech Cement",         "Cement"),
    Instrument("GRASIM",        "GRASIM.NS",        "Grasim Industries",        "Cement"),

    # ── Paint ───────────────────────────────────────────────────────
    Instrument("ASIANPAINT",    "ASIANPAINT.NS",    "Asian Paints",             "Paint"),
]

# ── Quick lookup helpers ──────────────────────────────────────────────

# All Kite symbols (for live trading watchlists)
KITE_SYMBOLS: list[str] = [i.kite_symbol for i in NIFTY50_INSTRUMENTS]

# All yfinance symbols (for backtesting and paper trading data)
YF_SYMBOLS: list[str] = [i.yf_symbol for i in NIFTY50_INSTRUMENTS]

# Convert Kite symbol → yfinance symbol
KITE_TO_YF: dict[str, str] = {i.kite_symbol: i.yf_symbol for i in NIFTY50_INSTRUMENTS}

# Convert yfinance symbol → Kite symbol
YF_TO_KITE: dict[str, str] = {i.yf_symbol: i.kite_symbol for i in NIFTY50_INSTRUMENTS}

# Symbol → sector mapping (useful for market analysis)
SYMBOL_TO_SECTOR: dict[str, str] = {i.kite_symbol: i.sector for i in NIFTY50_INSTRUMENTS}

# All unique sectors
SECTORS: list[str] = sorted(set(i.sector for i in NIFTY50_INSTRUMENTS))


def get_instrument(kite_symbol: str) -> Instrument | None:
    """Return the Instrument dataclass for a given Kite symbol."""
    return next((i for i in NIFTY50_INSTRUMENTS if i.kite_symbol == kite_symbol), None)


def get_symbols_by_sector(sector: str) -> list[str]:
    """Return all Kite symbols for a given sector."""
    return [i.kite_symbol for i in NIFTY50_INSTRUMENTS if i.sector == sector]
