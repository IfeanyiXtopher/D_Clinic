"""Parse date hints and format dates for SMS. Calendar ISO never goes in a reply."""

from __future__ import annotations

import re
from datetime import date, timedelta

_DAY_IN_TEXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\b", re.I)

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}
# Common words in the four program languages.
ALIASES = {
    "tomorrow": "tomorrow", "tomorow": "tomorrow",
    "gobe": "tomorrow",  # Hausa
    "ola": "tomorrow",  # Yoruba
    "next_week": "next_week", "next week": "next_week",
    "mako mai zuwa": "next_week",
    "ose to n bo": "next_week",
    "nxt week": "next_week",
}

_MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def is_clinic_day(d: date) -> bool:
    return d.weekday() < 5


def next_weekdays(as_of: date, n: int = 3, *, skip: date | None = None) -> list[date]:
    out: list[date] = []
    d = as_of + timedelta(days=1)
    while len(out) < n:
        if is_clinic_day(d) and d != skip:
            out.append(d)
        d += timedelta(days=1)
    return out


def format_sms_date(d: date) -> str:
    """Weekday + day + month. Not ISO — outbound PII scan rejects YYYY-MM-DD."""
    return f"{_DAY[d.weekday()]} {d.day} {_MONTH[d.month - 1]}"


def match_offered(text: str | None, hint: str | None, as_of: date,
                  offered: list[date] | None) -> date | None:
    """Map a spoken pick (wed 30, 30th, slot 3) onto one of the offered clinic days."""
    offered = list(offered or [])
    chosen = parse_date_hint(hint, as_of, offered)
    if chosen and chosen in offered:
        return chosen
    blob = " ".join(part for part in (text or "", hint or "") if part).lower()
    if not blob or not offered:
        return None
    for d in offered:
        label = format_sms_date(d).lower()
        short = f"{_DAY[d.weekday()].lower()} {d.day}"
        if label in blob or short in blob:
            return d
    hits: list[date] = []
    for num in _DAY_IN_TEXT.findall(blob):
        n = int(num)
        if n > 31:
            continue
        hits.extend(d for d in offered if d.day == n)
    uniq = list(dict.fromkeys(hits))
    if len(uniq) == 1:
        return uniq[0]
    for name, wd in WEEKDAYS.items():
        if re.search(rf"\b{re.escape(name)}\b", blob):
            matches = [d for d in offered if d.weekday() == wd]
            if len(matches) == 1:
                return matches[0]
    return None


def parse_date_hint(hint: str | None, as_of: date, offered: list[date] | None = None) -> date | None:
    if not hint:
        return None
    raw = hint.strip().lower().replace("_", " ")
    if raw.startswith("slot:"):
        try:
            idx = int(raw.split(":", 1)[1]) - 1
        except ValueError:
            return None
        if offered and 0 <= idx < len(offered):
            return offered[idx]
        return None
    if raw.isdigit() and offered:
        idx = int(raw) - 1
        if 0 <= idx < len(offered):
            return offered[idx]
        return None
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    if raw in {"tomorrow", *ALIASES} or ALIASES.get(raw) == "tomorrow":
        return as_of + timedelta(days=1)
    if raw in {"next week"} or ALIASES.get(raw) == "next_week":
        return next_weekdays(as_of + timedelta(days=6), 1)[0]
    if raw in WEEKDAYS:
        target = WEEKDAYS[raw]
        d = as_of + timedelta(days=1)
        for _ in range(8):
            if d.weekday() == target:
                return d
            d += timedelta(days=1)
    return None


def closed_day_hint(hint: str | None) -> bool:
    if not hint:
        return False
    raw = hint.strip().lower()
    return raw in {"saturday", "sunday", "sat", "sun"}
