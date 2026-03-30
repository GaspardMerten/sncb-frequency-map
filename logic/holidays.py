"""Belgian public holidays and school holiday calendar."""

from datetime import date, timedelta


def _easter(year: int) -> date:
    """Compute Easter Sunday for a given year (Anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def belgian_public_holidays(year: int) -> dict[date, str]:
    """Return all Belgian public holidays for a given year."""
    easter = _easter(year)
    return {
        date(year, 1, 1): "New Year",
        easter + timedelta(days=1): "Easter Monday",
        date(year, 5, 1): "Labour Day",
        easter + timedelta(days=39): "Ascension",
        easter + timedelta(days=50): "Whit Monday",
        date(year, 7, 21): "National Day",
        date(year, 8, 15): "Assumption",
        date(year, 11, 1): "All Saints",
        date(year, 11, 11): "Armistice",
        date(year, 12, 25): "Christmas",
    }


# School holidays: union of Flemish + French community periods
SCHOOL_HOLIDAYS = [
    (date(2024, 7, 1), date(2024, 8, 31), "Summer 2024"),
    (date(2024, 10, 28), date(2024, 11, 3), "Autumn 2024"),
    (date(2024, 12, 23), date(2025, 1, 5), "Christmas 2024"),
    (date(2025, 2, 24), date(2025, 3, 9), "Carnival 2025"),
    (date(2025, 4, 7), date(2025, 4, 20), "Easter 2025"),
    (date(2025, 7, 1), date(2025, 8, 31), "Summer 2025"),
    (date(2025, 10, 20), date(2025, 11, 2), "Autumn 2025"),
    (date(2025, 12, 22), date(2026, 1, 4), "Christmas 2025"),
    (date(2026, 2, 16), date(2026, 3, 1), "Carnival 2026"),
    (date(2026, 4, 6), date(2026, 5, 10), "Spring 2026"),
    (date(2026, 7, 1), date(2026, 8, 31), "Summer 2026"),
    (date(2026, 10, 19), date(2026, 11, 8), "Autumn 2026"),
    (date(2026, 12, 21), date(2027, 1, 3), "Christmas 2026"),
]


def is_school_holiday(d: date) -> str | None:
    """Return the school holiday name if the date falls in one, else None."""
    for start, end, name in SCHOOL_HOLIDAYS:
        if start <= d <= end:
            return name
    return None


def public_holidays_in_range(start: date, end: date) -> dict[date, str]:
    """All public holidays within [start, end]."""
    result = {}
    for y in range(start.year, end.year + 1):
        for d, name in belgian_public_holidays(y).items():
            if start <= d <= end:
                result[d] = name
    return result


def school_holidays_in_range(start: date, end: date) -> list[tuple[date, date, str]]:
    """School holiday periods overlapping [start, end], clipped to range."""
    result = []
    for s, e, name in SCHOOL_HOLIDAYS:
        if e >= start and s <= end:
            result.append((max(s, start), min(e, end), name))
    return result
