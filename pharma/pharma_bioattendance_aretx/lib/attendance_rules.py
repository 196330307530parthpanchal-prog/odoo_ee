"""
Pure-Python attendance rules (no Odoo imports) so they can be unit-tested
outside Odoo.  The Odoo glue code lives in models/attendance_engine.py.

CLIENT RULES IMPLEMENTED
------------------------
General Shift 09:00-18:30
    * Full day (PP)     : >= 9h20m worked           (real time, 1 minute counts)
    * 9h19m             : HD, except for the first 3 late entries of the month
    * Half day (HD)     : >= 4h45m  (leaving 13:45 after a 09:00 start)
    * Absent (A)        : <= 4h44m

Other shifts (Half day = total shift hours / 2)
    Shift A  06:00-14:30   full 8h30  half 4h15
    Shift B  14:00-22:30   full 8h30  half 4h15
    Shift C  22:00-06:30   full 8h30  half 4h15   (overnight)
    G1       09:30-19:00   full 9h30  half 4h45

Short Leave
    * Must be applied for by the employee (never automatic).
    * Valid only when >= 7h30m were worked (and the day is not already a PP).
    * Registered + valid -> the status shows the Time Off type's own
                            abbreviation (set in Odoo), with the day's
                            check-in / check-out times.
    * Not registered / not valid -> the shortfall is simply HD.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

# --------------------------------------------------------------------------
# TUNABLE CONSTANTS  (change here, nowhere else)
# --------------------------------------------------------------------------
GENERAL_GRACE_MAX_SHORTFALL_MIN = 1  # 9h19m  -> 1 minute short of 9h20m
SHORT_LEAVE_MIN_MINUTES = 7 * 60 + 30
# An IN/OUT pair longer than this is not a real working day - it is almost
# always a missing punch that shifted the odd/even pairing (e.g. 18:30 on
# Thursday paired with 09:00 on Monday).  Such a pair is treated as a
# mispunch (MP) instead of being counted as hours worked.
MAX_PAIR_MINUTES = 16 * 60
# 'span'  : working time = first check-in -> last check-out of the shift day
# 'sum'   : working time = sum of every completed IN/OUT pair
WORKING_TIME_MODE = "span"
# Window used to decide which shift day a punch belongs to.
SHIFT_WINDOW_BEFORE = timedelta(hours=3)
SHIFT_WINDOW_AFTER = timedelta(hours=2)

# --------------------------------------------------------------------------
# STATUS CODES
# --------------------------------------------------------------------------
PRESENT = "PP"
HALF_DAY = "HD"
ABSENT = "A"
WEEK_OFF = "WO"
HOLIDAY = "PH"
MISPUNCH = "MP"


@dataclass(frozen=True)
class ShiftRule:
    key: str
    name: str
    start_min: int  # minutes after midnight
    end_min: int  # minutes after midnight (may exceed 1440)
    full_min: int  # minutes needed for PP
    half_min: int  # minutes needed for HD
    is_general: bool = False

    @property
    def label(self):
        """Short text for the sheet's Shift row."""
        return {"general": "General", "a": "A", "b": "B", "c": "C", "g1": "G1"}.get(
            self.key, self.name
        )

    @property
    def overnight(self):
        return self.end_min > 1440

    @property
    def span_min(self):
        return self.end_min - self.start_min


def _mk(key, name, start, end, full=None, half=None, general=False):
    s = start[0] * 60 + start[1]
    e = end[0] * 60 + end[1]
    if e <= s:
        e += 1440
    span = e - s
    return ShiftRule(
        key,
        name,
        s,
        e,
        full if full is not None else span,
        half if half is not None else span // 2,
        general,
    )


SHIFT_RULES = {
    "general": _mk(
        "general",
        "General Shift",
        (9, 0),
        (18, 30),
        full=9 * 60 + 20,
        half=4 * 60 + 45,
        general=True,
    ),
    "a": _mk("a", "Shift A", (6, 0), (14, 30)),
    "b": _mk("b", "Shift B", (14, 0), (22, 30)),
    "c": _mk("c", "Shift C", (22, 0), (6, 30)),
    "g1": _mk("g1", "G1 Shift", (9, 30), (19, 0)),
}


def match_rule(calendar_name):
    """Return the ShiftRule for a Working Schedule name, or None."""
    n = " ".join((calendar_name or "").lower().split())
    if not n:
        return None
    if "general" in n:
        return SHIFT_RULES["general"]
    if re.search(r"\bg\s*-?\s*1\b", n):
        return SHIFT_RULES["g1"]
    m = re.search(r"\bshift\s*-?\s*([abc])\b", n)
    if m:
        return SHIFT_RULES[m.group(1)]
    return None


def _fmt_hm(minutes):
    minutes %= 1440
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def window_text(rule):
    return "%s %s-%s" % (rule.name, _fmt_hm(rule.start_min), _fmt_hm(rule.end_min))


def combine_rules(rule_list):
    """
    Rule for a day on which the employee is rostered for MORE THAN ONE shift
    (normal Working Hours + an Extra Shift).

        required full day = sum of each shift's full-day minutes
                            minus the minutes the shift windows overlap
                            (overlap time can only be worked once)
        required half day = sum of each shift's half-day minutes
                            minus half of that overlap

    Example  Shift A 06:00-14:30 + Shift B 14:00-22:30
        full = 510 + 510 - 30 = 990  (16h30)      half = 255 + 255 - 15 = 495
    """
    unique, seen = [], set()
    for r in sorted(rule_list, key=lambda r: (r.start_min, r.end_min)):
        if (r.key, r.name, r.start_min, r.end_min) not in seen:
            seen.add((r.key, r.name, r.start_min, r.end_min))
            unique.append(r)
    if len(unique) == 1:
        return unique[0]

    merged = []
    for r in unique:  # union length of the windows
        if merged and r.start_min <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], r.end_min)
        else:
            merged.append([r.start_min, r.end_min])
    union_len = sum(e - s for s, e in merged)
    overlap = sum(r.span_min for r in unique) - union_len

    return ShiftRule(
        "combined",
        " + ".join(r.name for r in unique),
        min(r.start_min for r in unique),
        max(r.end_min for r in unique),
        sum(r.full_min for r in unique) - overlap,
        sum(r.half_min for r in unique) - overlap // 2,
        False,
    )


def pair_limit_minutes(rule):
    """Longest IN/OUT pair that is still believable for this day's rule."""
    return max(MAX_PAIR_MINUTES, rule.span_min + 3 * 60)


def generic_rule(name, start_min, end_min, hours_per_day):
    """Fallback for calendars that are not one of the client shifts."""
    if end_min <= start_min:
        end_min += 1440
    full = int(round((hours_per_day or (end_min - start_min) / 60.0) * 60))
    return ShiftRule(
        "generic", name or "Working Hours", start_min, end_min, full, full // 2, False
    )


# --------------------------------------------------------------------------
# LEAVES
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class LeaveInfo:
    code: str
    kind: str  # 'full' | 'half_am' | 'half_pm' | 'short'
    minutes: int = 0


def is_short_leave(name, abbreviation):
    """Short Leave is detected by name/abbreviation but NEVER by plain 'SL'
    because 'SL' is the client's Sick Leave abbreviation."""
    n = (name or "").strip().lower()
    a = (abbreviation or "").strip().upper().replace(" ", "")
    if "sick" in n:
        return False
    return "short" in n or a in ("SHORT", "SHORTLEAVE", "SH")


# --------------------------------------------------------------------------
# SHIFT DAY ASSIGNMENT
# --------------------------------------------------------------------------
def shift_window(rule, day):
    start = datetime.combine(day, time.min) + timedelta(minutes=rule.start_min)
    end = datetime.combine(day, time.min) + timedelta(minutes=rule.end_min)
    return start, end


def assign_shift_day(check_in_local, rule_for_date):
    """
    Decide which *shift day* a check-in belongs to.

    A night shift that starts 22:00 on the 1st and ends 06:30 on the 2nd is
    one shift of the 1st.  Candidates are the punch's calendar day and the
    day before; the candidate whose shift start is closest wins, provided
    the punch lies inside that shift's window.  Otherwise: calendar day.
    """
    x = check_in_local.date()
    best, best_dist = None, None
    for day in (x - timedelta(days=1), x):
        rule = rule_for_date(day)
        if not rule:
            continue
        start, end = shift_window(rule, day)
        if start - SHIFT_WINDOW_BEFORE <= check_in_local <= end + SHIFT_WINDOW_AFTER:
            dist = abs((check_in_local - start).total_seconds())
            if best is None or dist < best_dist:
                best, best_dist = day, dist
    return best or x


def summarise_punches(pairs, max_pair_minutes=None, mode=None):
    """
    pairs: list of (check_in_local, check_out_local|None)
    max_pair_minutes: longest believable single IN/OUT pair
                      (defaults to MAX_PAIR_MINUTES)
    mode: 'span' | 'sum' (defaults to WORKING_TIME_MODE)
    Returns dict(first_in, last_out, minutes, has_pair, has_open)
    """
    mode = mode or WORKING_TIME_MODE
    max_td = timedelta(minutes=max_pair_minutes or MAX_PAIR_MINUTES)
    valid = [(i, o) for i, o in pairs if o and o > i and (o - i) <= max_td]
    has_open = any((not o) or o <= i or (o - i) > max_td for i, o in pairs)
    first_in = min((i for i, _ in pairs), default=None)
    last_out = max((o for _, o in valid), default=None)
    minutes = None
    if valid:
        if mode == "sum":
            secs = sum((o - i).total_seconds() for i, o in valid)
        else:
            secs = (max(o for _, o in valid) - min(i for i, _ in valid)).total_seconds()
        minutes = int(secs // 60)  # real-time: seconds are truncated
    return {
        "first_in": first_in,
        "last_out": last_out,
        "minutes": minutes,
        "has_pair": bool(valid),
        "has_open": has_open,
    }


def is_late_entry(rule, first_in):
    """Check-in later than the shift start (to the minute)."""
    if not first_in:
        return False
    start, _ = shift_window(rule, first_in.date())
    first_in_min = first_in.replace(second=0, microsecond=0)
    return first_in_min > start


# --------------------------------------------------------------------------
# STATUS
# --------------------------------------------------------------------------
def _half_leave_code(halves, worked_ok):
    """halves: list[LeaveInfo] with kind half_am / half_pm."""
    am = next((l for l in halves if l.kind == "half_am"), None)
    pm = next((l for l in halves if l.kind == "half_pm"), None)
    if am and pm:
        return "%s/%s" % (am.code, pm.code)
    present = "P" if worked_ok else "A"
    if am:
        return "%s/%s" % (am.code, present)
    return "%s/%s" % (present, pm.code)


def evaluate_day(rule, **kwargs):
    """Return the attendance-sheet status string for one employee-day."""
    return evaluate_day_detail(rule, **kwargs)[0]


def evaluate_day_detail(
    rule,
    *,
    working,
    holiday=False,
    summary=None,
    leaves=(),
    grace_available=False,
    is_future=False
):
    """Return (status, kind).  kind == 'short' when a registered Short
    Leave was applied (so the sheet can colour it), else ''."""
    summary = summary or {}
    minutes = summary.get("minutes")
    has_pair = summary.get("has_pair", False)
    has_open = summary.get("has_open", False)

    # ------------------------------------------------------------------
    # WEEK OFF / WEEKEND HANDLING
    # ------------------------------------------------------------------
    #
    # General Shift:
    #   - No attendance on a non-working day -> WO
    #   - Attendance exists -> calculate PP / HD / A normally
    #
    # Other shifts:
    #   - These shifts run every day.
    #   - No attendance -> A
    #   - Attendance exists -> calculate PP / HD / A normally
    #
    # Therefore, a calendar week-off must NOT override actual biometric
    # attendance.
    # ------------------------------------------------------------------

    if not working:
        if not summary.get("has_pair"):
            if rule.is_general:
                return WEEK_OFF, ""
            return ABSENT, ""

        # There is a completed attendance pair on the weekend.
        # Do NOT return WO. Continue through the normal attendance
        # calculation below.

    full = [l for l in leaves if l.kind == "full"]
    short = [l for l in leaves if l.kind == "short"]
    halves = [l for l in leaves if l.kind in ("half_am", "half_pm")]

    # ------------------------------------------------------------------
    # FULL-DAY APPROVED LEAVE HAS PRIORITY OVER ATTENDANCE
    # ------------------------------------------------------------------
    # If an approved full-day leave exists for this employee/date,
    # the Attendance Sheet must show the leave even when biometric
    # check-in/check-out records are present.
    #
    # Attendance records are NOT deleted or modified.
    # The approved Time Off simply takes priority for the sheet status.
    # ------------------------------------------------------------------
    if full:
        return full[0].code, ""

    # ---- No usable punches ----------------------------------------------
    if not has_pair:

        if halves:
            return _half_leave_code(halves, worked_ok=False), ""

        if has_open:
            return MISPUNCH, ""

        return ABSENT, ""

    # ---- Worked (full-day leave is overridden, same as the attendance hook)
    if halves:
        am = any(l.kind == "half_am" for l in halves)
        pm = any(l.kind == "half_pm" for l in halves)
        if am and pm:
            return _half_leave_code(halves, worked_ok=True), ""
        return _half_leave_code(halves, worked_ok=minutes >= rule.half_min), ""

    if minutes >= rule.full_min:
        return PRESENT, ""

    # -------------------------------------------------------------
    # SHORT LEAVE
    #
    # Short Leave is applicable ONLY for General Shift.
    #
    # The employee must have actually registered/applied for
    # Short Leave.
    #
    # Actual worked time + registered Short Leave duration
    # must be at least 7h30m.
    # -------------------------------------------------------------
    if rule.is_general and short:
        short_leave_minutes = sum(leave.minutes for leave in short)

        total_minutes_with_short_leave = minutes + short_leave_minutes

        if (
            total_minutes_with_short_leave >= SHORT_LEAVE_MIN_MINUTES
            and minutes < rule.full_min
        ):
            return short[0].code, "short"

    if minutes >= rule.half_min:
        return HALF_DAY, ""
    return ABSENT, ""


# --------------------------------------------------------------------------
# COLOURS  (used by the XLSX renderer)
# --------------------------------------------------------------------------
# (background, font colour, bold)
PALETTE = {
    "present": ("#00B050", "#FFFFFF", True),  # PP
    "half_day": ("#FFC000", "#000000", True),  # HD
    "absent": ("#FF5050", "#FFFFFF", True),  # A
    "week_off": ("#BDD7EE", "#1F3864", False),  # WO
    "holiday": ("#D9C2F0", "#3B1F6B", False),  # PH
    "leave": ("#FFE699", "#000000", False),  # CL / SL / EL / CO ...
    "short": ("#9DDCD0", "#000000", False),  # Short Leave (abbreviation from Odoo)
    "half_leave": ("#C5E0B4", "#000000", False),  # CL/P  P/CL  SL/P ...
    "half_abs": ("#F8CBAD", "#000000", False),  # CL/A  A/CL
    "mispunch": ("#ED7D31", "#FFFFFF", True),  # MP
    "blank": (None, "#000000", False),
}

LEGEND = [
    ("PP", "present", "Present - full day completed"),
    ("HD", "half_day", "Half day (worked at least half the shift, not full)"),
    ("A", "absent", "Absent (below half-day minimum / no punches)"),
    ("WO", "week_off", "Weekly off"),
    ("PH", "holiday", "Public holiday"),
    ("CL / SL / EL / CO", "leave", "Approved full-day leave (Time Off abbreviation)"),
    (
        "<Short Leave abbr.>",
        "short",
        "Short Leave registered in Odoo and 7h30m or more worked; shows the abbreviation set on the Time Off type. Not registered = HD",
    ),
    ("CL/P  P/CL", "half_leave", "Half-day leave + present for the other half"),
    ("CL/A  A/CL", "half_abs", "Half-day leave + absent for the other half"),
    (
        "MP",
        "mispunch",
        "Mispunch - missing/implausible punch (e.g. pair longer than 16h), needs HR correction",
    ),
]


def status_category(code, kind=""):
    if kind == "short":
        return "short"
    c = (code or "").strip().upper()
    if not c:
        return "blank"
    if c == PRESENT:
        return "present"
    if c == HALF_DAY:
        return "half_day"
    if c == ABSENT:
        return "absent"
    if c == WEEK_OFF:
        return "week_off"
    if c == HOLIDAY:
        return "holiday"
    if c == MISPUNCH:
        return "mispunch"
    if "/" in c:
        parts = c.split("/")
        if "A" in parts:
            return "half_abs"
        return "half_leave"
    return "leave"


def total_days(statuses, days_in_range):
    """Python twin of the Excel Total formula (used as cached value)."""
    ded = 0.0
    for s in statuses:
        c = (s or "").strip().upper()
        if c in ("A", "LWP", "--", "X", MISPUNCH):
            ded += 1
        elif c == HALF_DAY:
            ded += 0.5
        elif "/" in c:
            a, b = c.split("/", 1)
            if a in ("A", "LWP", "--", "X") or b in ("A", "LWP", "--", "X"):
                ded += 0.5
    return days_in_range - ded
