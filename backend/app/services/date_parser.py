"""Natural language date parser for conversational booking.
Operates relative to the organization local timezone (Asia/Kolkata).
"""
import re
from datetime import date, datetime, time, timedelta

from app.core.timeutils import now_local

WEEKDAYS_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTHS_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_natural_date(text: str, base_date: date | None = None) -> date | None:
    """Parse natural language date strings like:
    - 'today', 'tomorrow', 'day after tomorrow'
    - 'in 2 days', 'in 3 days'
    - 'monday', 'next monday', 'this friday'
    - '2026-10-27' (ISO)
    - '27-10-2026', '27/10/2026'
    - '27 Oct', '27th Oct', '27 October 2026'
    - 'Oct 27', 'October 27th'
    """
    if not text:
        return None
    raw = text.strip().lower()
    today = base_date or now_local().date()

    # 1. Relative keywords
    if re.search(r"\b(day after tomorrow|day after tmrw)\b", raw):
        return today + timedelta(days=2)
    if re.search(r"\b(tomorrow|tmrw|tomorow)\b", raw):
        return today + timedelta(days=1)
    if re.search(r"\b(today|this day)\b", raw):
        return today
    if re.search(r"\b(day before yesterday)\b", raw):
        return today - timedelta(days=2)
    if re.search(r"\b(yesterday)\b", raw):
        return today - timedelta(days=1)

    in_days_m = re.search(r"\bin\s+(\d+)\s+days?\b", raw)
    if in_days_m:
        return today + timedelta(days=int(in_days_m.group(1)))

    # 2. Weekdays ("next monday", "this friday", "monday", "last friday")
    # Sort names by length descending so e.g. "thursday" matches before "thu"
    sorted_weekdays = sorted(WEEKDAYS_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)
    for name, target_wd in sorted_weekdays:
        if re.search(rf"\blast\s+{name}\b", raw):
            cur_wd = today.weekday()
            diff = (target_wd - cur_wd) % 7
            diff = diff - 7 if diff > 0 else -7
            return today + timedelta(days=diff)
        if re.search(rf"\b(next|this|coming|on|to)?\s*{name}\b", raw):
            is_next = bool(re.search(rf"\bnext\s+{name}\b", raw))
            cur_wd = today.weekday()
            diff = (target_wd - cur_wd) % 7
            if is_next:
                diff += 7 if diff > 0 else 7
            elif diff == 0:
                diff = 7
            return today + timedelta(days=diff)

    # 3. ISO date: YYYY-MM-DD
    iso_m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", raw)
    if iso_m:
        try:
            return date(int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3)))
        except ValueError:
            pass

    # 4. DD-MM-YYYY or DD/MM/YYYY
    dmy_m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", raw)
    if dmy_m:
        try:
            return date(int(dmy_m.group(3)), int(dmy_m.group(2)), int(dmy_m.group(1)))
        except ValueError:
            pass

    # 5. DD Mon [YYYY] e.g. "27th October", "27 Oct 2026", "27th Oct"
    for m_name, m_num in MONTHS_MAP.items():
        pattern1 = rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{m_name}(?:\s+(\d{{4}}))?\b"
        m1 = re.search(pattern1, raw)
        if m1:
            try:
                day_num = int(m1.group(1))
                year_num = int(m1.group(2)) if m1.group(2) else today.year
                d = date(year_num, m_num, day_num)
                # If no year was given and date is in the past, assume next year
                if not m1.group(2) and d < today:
                    d = date(year_num + 1, m_num, day_num)
                return d
            except ValueError:
                pass

        # Pattern 2: "Oct 27", "October 27th [YYYY]"
        pattern2 = rf"\b{m_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b"
        m2 = re.search(pattern2, raw)
        if m2:
            try:
                day_num = int(m2.group(1))
                year_num = int(m2.group(2)) if m2.group(2) else today.year
                d = date(year_num, m_num, day_num)
                if not m2.group(2) and d < today:
                    d = date(year_num + 1, m_num, day_num)
                return d
            except ValueError:
                pass

    return None


def parse_time_preference(text: str) -> dict:
    """Extract time of day (morning/afternoon/evening), specific target time (e.g. 10:00 AM),
    or earliest/latest preference from natural language requests.
    
    Standardized ranges:
    - morning: start_at < 12:00 PM
    - afternoon: 12:00 PM <= start_at < 05:00 PM
    - evening: start_at >= 05:00 PM
    """
    if not text:
        return {"time_of_day": None, "target_time": None, "earliest": False, "latest": False}
    raw = text.strip().lower()
    res = {"time_of_day": None, "target_time": None, "earliest": False, "latest": False}

    # 1. Earliest / Latest
    if re.search(r"\b(earliest|first\s+available|first\s+slot|as\s+early\s+as\s+possible)\b", raw):
        res["earliest"] = True
    elif re.search(r"\b(latest|last\s+available|last\s+slot|as\s+late\s+as\s+possible)\b", raw):
        res["latest"] = True

    # 2. Specific time like '10 AM', '10:30 am', '2 pm', '2:30 PM', 'at 11'
    m_time = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", raw)
    if m_time:
        hr = int(m_time.group(1))
        mn = int(m_time.group(2) or 0)
        ampm = m_time.group(3).lower()
        if ampm == "pm" and hr < 12:
            hr += 12
        elif ampm == "am" and hr == 12:
            hr = 0
        try:
            res["target_time"] = time(hr, mn)
            if hr < 12:
                res["time_of_day"] = "morning"
            elif hr < 17:
                res["time_of_day"] = "afternoon"
            else:
                res["time_of_day"] = "evening"
            return res
        except ValueError:
            pass

    # 'at <hour>' e.g. 'at 10', 'at 2'
    m_at = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", raw)
    if m_at:
        hr = int(m_at.group(1))
        mn = int(m_at.group(2) or 0)
        if 1 <= hr <= 6:
            hr += 12  # assume PM during typical reception hours
        try:
            res["target_time"] = time(hr, mn)
            if hr < 12:
                res["time_of_day"] = "morning"
            elif hr < 17:
                res["time_of_day"] = "afternoon"
            else:
                res["time_of_day"] = "evening"
            return res
        except ValueError:
            pass

    # 3. Time of day ranges
    if re.search(r"\b(morning|mornings|in the morning|am)\b", raw):
        res["time_of_day"] = "morning"
    elif re.search(r"\b(afternoon|afternoons|in the afternoon|post noon|noon)\b", raw):
        res["time_of_day"] = "afternoon"
    elif re.search(r"\b(evening|evenings|in the evening)\b", raw):
        res["time_of_day"] = "evening"

    return res
