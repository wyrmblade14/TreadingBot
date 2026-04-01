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
NSE_HOLIDAYS: set[date] = {
    # ── 2024 ──────────────────────────────────────────────────────────
    date(2024, 1, 22),   # Ram Mandir consecration (special closure)
    date(2024, 1, 26),   # Republic Day
    date(2024, 3, 25),   # Holi
    date(2024, 3, 29),   # Good Friday
    date(2024, 4, 14),   # Dr. Ambedkar Jayanti / Ram Navami
    date(2024, 4, 17),   # Ram Navami
    date(2024, 4, 21),   # Mahavir Jayanti
    date(2024, 5, 23),   # Buddha Purnima
    date(2024, 6, 17),   # Eid ul-Adha (Bakri Eid)
    date(2024, 7, 17),   # Muharram
    date(2024, 8, 15),   # Independence Day
    date(2024, 10, 2),   # Gandhi Jayanti / Mahatma Gandhi Birthday
    date(2024, 11, 1),   # Diwali Laxmi Puja (Muhurat trading exception)
    date(2024, 11, 15),  # Gurunanak Jayanti
    date(2024, 12, 25),  # Christmas

    # ── 2025 ──────────────────────────────────────────────────────────
    date(2025, 2, 26),   # Mahashivratri
    date(2025, 3, 14),   # Holi
    date(2025, 3, 31),   # Id-ul-Fitr (Ramadan Eid)
    date(2025, 4, 10),   # Shri Ram Navami
    date(2025, 4, 14),   # Dr. Ambedkar Jayanti
    date(2025, 4, 18),   # Good Friday
    date(2025, 5, 1),    # Maharashtra Day
    date(2025, 8, 15),   # Independence Day
    date(2025, 8, 27),   # Ganesh Chaturthi
    date(2025, 10, 2),   # Gandhi Jayanti / Mahatma Gandhi Birthday
    date(2025, 10, 21),  # Diwali Amavasya (Laxmi Puja)
    date(2025, 10, 22),  # Diwali (Balipratipada)
    date(2025, 10, 28),  # Gurunanak Jayanti (tentative)
    date(2025, 11, 5),   # Gurunanak Jayanti
    date(2025, 12, 25),  # Christmas

    # ── 2026 (tentative — update when NSE publishes official list) ────
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Mahashivratri (approx)
    date(2026, 4, 3),    # Good Friday (approx)
    date(2026, 8, 15),   # Independence Day
    date(2026, 10, 2),   # Gandhi Jayanti
    date(2026, 12, 25),  # Christmas
}


def is_trading_day(d: date | None = None) -> bool:
    """
    Return True if the given date is a regular NSE trading day.

    A trading day is a weekday (Mon–Fri) that is NOT in the holiday list.

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
    if d.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    return d not in NSE_HOLIDAYS


def next_trading_day(from_date: date | None = None) -> date:
    """Return the next trading day on or after from_date."""
    d = from_date or date.today()
    while not is_trading_day(d):
        from datetime import timedelta
        d += timedelta(days=1)
    return d
