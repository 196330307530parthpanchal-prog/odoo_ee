from datetime import date


# ============================================================
# OVERTIME POLICY
# ============================================================

# OT requires minimum 2 hours of EXTRA working.
OT_MIN_EXTRA_MINUTES = 2 * 60


# ============================================================
# COMPENSATORY OFF POLICY
# ============================================================

# C-Off eligibility is based on EXTRA working, not total worked time.
#
# Sr. Executive & Below:
#     minimum 6 hours 30 minutes extra
#
# Above Sr. Executive:
#     minimum 8 hours 30 minutes extra
COFF_MIN_EXTRA_MINUTES = {
    'below': 6 * 60 + 30,
    'above': 8 * 60 + 30,
}

# Maximum C-Offs that can be availed in one calendar month.
COFF_MAX_AVAILED_PER_MONTH = 2


# ============================================================
# OT SUBMISSION DEADLINE
# ============================================================

# OT must be submitted before the 15th of the following month.
SUBMIT_BEFORE_DAY = 15


# ============================================================
# JOB POSITION C-OFF LEVELS
# ============================================================

GRADES = [
    ('below', 'Sr. Executive & Below'),
    ('above', 'Above Sr. Executive'),
]


# ============================================================
# HELPERS
# ============================================================

def submission_deadline(work_date):
    """
    Return the OT submission deadline.

    Example:
        Work date = 10/09/2026
        Deadline  = 15/10/2026
    """
    if not work_date:
        return False

    if work_date.month == 12:
        return date(
            work_date.year + 1,
            1,
            SUBMIT_BEFORE_DAY,
        )

    return date(
        work_date.year,
        work_date.month + 1,
        SUBMIT_BEFORE_DAY,
    )


def is_in_time(work_date, submit_date):
    """
    Return True when the OT request is submitted before
    the 15th of the following month.
    """
    if not work_date or not submit_date:
        return False

    deadline = submission_deadline(work_date)

    return submit_date < deadline


def min_extra_minutes(request_type, grade='below'):
    """
    Return the minimum EXTRA working minutes required.

    OT:
        2:00

    C-Off:
        below = 6:30
        above = 8:30
    """
    request_type = (request_type or '').strip().lower()

    if request_type == 'ot':
        return OT_MIN_EXTRA_MINUTES

    if request_type == 'coff':
        return COFF_MIN_EXTRA_MINUTES.get(
            grade or 'below',
            COFF_MIN_EXTRA_MINUTES['below'],
        )

    return 0


def extra_minutes(worked_minutes, regular_required_minutes):
    """
    Calculate EXTRA working.

    IMPORTANT:
        Extra working is NOT total worked time.

        Extra = Worked - Regular Required

    The result can never be negative.
    """
    worked_minutes = int(worked_minutes or 0)
    regular_required_minutes = int(
        regular_required_minutes or 0
    )

    return max(
        0,
        worked_minutes - regular_required_minutes,
    )


def hm(minutes):
    """Convert minutes to H:MM."""
    minutes = int(minutes or 0)

    return '%d:%02d' % (
        minutes // 60,
        minutes % 60,
    )


def is_extra_working_eligible(
    request_type,
    extra_working_minutes,
    grade='below',
):
    """Check whether the employee has enough extra working."""
    required_minutes = min_extra_minutes(
        request_type,
        grade,
    )

    return int(extra_working_minutes or 0) >= required_minutes


def eligibility_error(
    request_type,
    grade,
    extra_working_minutes,
):
    """
    Return a readable eligibility error.
    Return empty string when eligible.
    """
    request_type = (request_type or '').strip().lower()

    required_minutes = min_extra_minutes(
        request_type,
        grade,
    )

    actual_minutes = int(
        extra_working_minutes or 0
    )

    if actual_minutes >= required_minutes:
        return ''

    if request_type == 'ot':
        label = 'Overtime'
    elif request_type == 'coff':
        label = 'Compensatory Off'
    else:
        label = 'This request'

    return (
        '%s requires at least %s of extra working.\n\n'
        'Required extra working: %s\n'
        'Actual extra working: %s'
        % (
            label,
            hm(required_minutes),
            hm(required_minutes),
            hm(actual_minutes),
        )
    )


def coff_monthly_limit():
    """Maximum C-Offs allowed per month."""
    return COFF_MAX_AVAILED_PER_MONTH