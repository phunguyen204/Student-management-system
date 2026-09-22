"""Schedule parsing and conflict detection for class sections.

Supports multiple sessions per class separated by ';' or ','.
Each session specifies a weekday and time range.
"""
import re


def parse_schedule(value):
    """Return (weekday, start_minutes, end_minutes), or None for invalid input.

    One session per course is supported until the semester/section model exists.
    Accepted examples: Thu 2 7h-9h, Thứ 2 7h30-9h30, CN 8-10,
    Mon 7-9AM and Tue 13:00-15:00. Never silently ignore trailing sessions.
    """
    match = re.fullmatch(
        r"\s*(?:(?:Thu|Thứ)\s*([2-7])|(CN)|(Mon|Tue|Wed|Thu|Fri|Sat|Sun))"
        r"\s+(\d{1,2})(?:[h:](\d{0,2}))?\s*-\s*"
        r"(\d{1,2})(?:[h:](\d{0,2}))?\s*(AM|PM)?\s*",
        str(value or ""), re.IGNORECASE,
    )
    if not match:
        return None
    day, sunday, english, sh, sm, eh, em, period = match.groups()
    weekday = int(day) if day else 8 if sunday else {
        "mon": 2, "tue": 3, "wed": 4, "thu": 5,
        "fri": 6, "sat": 7, "sun": 8,
    }[english.lower()]
    sh, eh, sm, em = int(sh), int(eh), int(sm or 0), int(em or 0)
    if sm > 59 or em > 59:
        return None
    if period:
        if not (1 <= sh <= 12 and 1 <= eh <= 12):
            return None
        sh, eh = sh % 12, eh % 12
        if period.upper() == "PM":
            sh += 12
            eh += 12
    if sh > 23 or eh > 23:
        return None
    start, end = sh * 60 + sm, eh * 60 + em
    return (weekday, start, end) if start < end else None


def parse_multi_schedule(value):
    """Parse one or more sessions separated by ';' or ','.

    Returns a list of (weekday, start_minutes, end_minutes) tuples,
    or None if *any* session is invalid or the input is empty.

    Examples:
        "Thu 2 7h-9h; Thu 4 13h-15h"  -> [(2,420,540), (5,780,900)]
        "Thu 2 7h-9h"                  -> [(2,420,540)]
        ""                             -> None
        "Thu 2 7h-9h; bad"             -> None
    """
    if not value or not str(value).strip():
        return None
    parts = re.split(r'[;,]', str(value))
    sessions = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        parsed = parse_schedule(part)
        if parsed is None:
            return None
        sessions.append(parsed)
    return sessions if sessions else None


def sessions_overlap(a, b):
    """Check if two individual sessions (weekday, start, end) overlap."""
    if a[0] != b[0]:
        return False
    return a[1] < b[2] and a[2] > b[1]


def schedule_conflicts(schedule_a, schedule_b):
    """Check if any session in schedule_a conflicts with any in schedule_b.

    Each schedule is a list of (weekday, start_minutes, end_minutes).
    Returns the first conflicting pair (session_a, session_b) or None.
    """
    if not schedule_a or not schedule_b:
        return None
    for sa in schedule_a:
        for sb in schedule_b:
            if sessions_overlap(sa, sb):
                return (sa, sb)
    return None


def format_session(weekday, start_minutes, end_minutes):
    """Format a single session as a human-readable string."""
    day_names = {2: "Thứ 2", 3: "Thứ 3", 4: "Thứ 4", 5: "Thứ 5",
                 6: "Thứ 6", 7: "Thứ 7", 8: "CN"}
    day = day_names.get(weekday, f"Ngày {weekday}")
    sh, sm = divmod(start_minutes, 60)
    eh, em = divmod(end_minutes, 60)
    start_str = f"{sh}h{sm:02d}" if sm else f"{sh}h"
    end_str = f"{eh}h{em:02d}" if em else f"{eh}h"
    return f"{day} {start_str}-{end_str}"


def format_schedule_list(sessions):
    """Format a list of sessions into a semicolon-separated string."""
    if not sessions:
        return ""
    return "; ".join(format_session(*s) for s in sessions)
