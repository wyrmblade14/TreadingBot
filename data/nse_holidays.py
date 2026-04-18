"""
NSE Trading Holiday Calendar.

NSE publishes a list of market holidays each year. On these days the exchange
is closed and no trading occurs. The scheduler uses this to skip all jobs
on holidays so it doesn't waste API calls or log confusing "no data" errors.

How to update each year:
  1. Visit https://www.nseindia.com/resources/exchange-communication-holidays
  2. Add the new year's dates to NSE_HOLIDAYS below (format: "YYYY-MM-DD")
  3. Remove dates older than 2 years to keep the list short

Current coverage: 2024, 2025, 2026
"""

from __future__ import annotations

from datetime import date

# Official NSE equity segment holidays
# Source: NSE circular on exchange holidays
NSE_HOLIDAYS: dict[date, str] = {
    # ── 2024 ──────────────────────────────────────────────────────────
    date(2024, 1, 22):  "Ram Mandir Consecration",
    date(2024, 1, 26):  "Republic Day",
    date(2024, 3, 25):  "Holi",
    date(2024, 3, 29):  "Good Friday",
    date(2024, 4, 11):  "Id-ul-Fitr (Ramadan Eid)",
    date(2024, 4, 17):  "Shri Ram Navami",
    date(2024, 4, 21):  "Mahavir Jayanti",
    date(2024, 5, 23):  "Buddha Purnima",
    date(2024, 6, 17):  "Bakri Id",
    date(2024, 7, 17):  "Muharram",
    date(2024, 8, 15):  "Independence Day",
    date(2024, 10, 2):  "Mahatma Gandhi Jayanti",
    date(2024, 11, 1):  "Diwali Laxmi Pujan",
    date(2024, 11, 15): "Gurunanak Jayanti",
    date(2024, 12, 25): "Christmas",

    # ── 2025 ──────────────────────────────────────────────────────────
    date(2025, 2, 26):  "Mahashivratri",
    date(2025, 3, 14):  "Holi",
    date(2025, 3, 31):  "Id-ul-Fitr (Ramadan Eid)",
    date(2025, 4, 10):  "Shri Ram Navami",
    date(2025, 4, 14):  "Dr. Ambedkar Jayanti",
    date(2025, 4, 18):  "Good Friday",
    date(2025, 5, 1):   "Maharashtra Day",
    date(2025, 8, 15):  "Independence Day",
    date(2025, 8, 27):  "Ganesh Chaturthi",
    date(2025, 10, 2):  "Mahatma Gandhi Jayanti",
    date(2025, 10, 21): "Diwali Amavasya (Laxmi Pujan)",
    date(2025, 10, 22): "Diwali Balipratipada",
    date(2025, 11, 5):  "Gurunanak Jayanti",
    date(2025, 12, 25): "Christmas",

    # ── 2026 ──────────────────────────────────────────────────────────
    date(2026, 1, 26):  "Republic Day",
    date(2026, 3, 3):   "Mahashivratri",
    date(2026, 3, 20):  "Id-ul-Fitr (Ramadan Eid)",
    date(2026, 4, 3):   "Good Friday",
    date(2026, 4, 14):  "Dr. Ambedkar Jayanti",
    # date(2026, 4, 15):  "Ram Navami",  # NSE did not close — removed
    date(2026, 5, 1):   "Maharashtra Day",
    date(2026, 8, 15):  "Independence Day",
    date(2026, 8, 17):  "Ganesh Chaturthi",
    date(2026, 10, 2):  "Mahatma Gandhi Jayanti",
    date(2026, 11, 9):  "Diwali Laxmi Pujan",
    date(2026, 11, 10): "Diwali Balipratipada",
    date(2026, 11, 25): "Gurunanak Jayanti",
    date(2026, 12, 25): "Christmas",
}


# Special weekend trading sessions (e.g., Muhurat trading on weekends, DR site testing)
# Add dates here if a weekend session is announced by NSE.
SPECIAL_WEEKEND_TRADING: set[date] = set()

def is_trading_day(d: date | None = None) -> bool:
    """
    Return True if the given date is a regular NSE trading day.

    A trading day is a weekday (Mon–Fri) that is NOT in the holiday list,
    or a weekend day explicitly listed in SPECIAL_WEEKEND_TRADING.

    Args:
        d: Date to check. Defaults to today.

    Returns:
        True if markets are open, False if closed (weekend or holiday).

    Example:
        >>> from datetime import date
        >>> is_trading_day(date(2025, 3, 14))   # Holi
        False
        >>> is_trading_day(date(2025, 3, 17))   # Monday
        True
    """
    if d is None:
        d = date.today()
        
    # If the date is explicitly an NSE holiday, the market is closed
    if d in NSE_HOLIDAYS:
        return False
        
    # If it's a weekend (Saturday=5, Sunday=6)
    if d.weekday() >= 5:
        # Check if there is a special weekend trading session (like Muhurat trading)
        if d in SPECIAL_WEEKEND_TRADING:
            return True
        return False
        
    return True

def is_holiday(d: date | None = None) -> bool:
    """
    Return True if the given date is a holiday or a non-trading weekend.
    This acts as the exact inverse of is_trading_day.
    """
    return not is_trading_day(d)

def get_holiday_reason(d: date | None = None) -> str:
    """Return the name of the holiday or 'Weekend' if market is closed."""
    if d is None:
        d = date.today()
    
    if d in NSE_HOLIDAYS:
        return NSE_HOLIDAYS[d]
    
    if d.weekday() == 5:
        return "Weekend (Saturday)"
    if d.weekday() == 6:
        return "Weekend (Sunday)"
    
    return ""


def next_trading_day(from_date: date | None = None) -> date:
    """Return the next trading day on or after from_date."""
    d = from_date or date.today()
    while not is_trading_day(d):
        from datetime import timedelta
        d += timedelta(days=1)
    return d
