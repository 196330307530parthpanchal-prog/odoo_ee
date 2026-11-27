"""
Attendance engine for Pharma Biometric Attendance.

IMPORTANT ARCHITECTURE
----------------------
* Planning is the source of assigned shifts.
* hr.attendance remains the source of actual IN/OUT punches.
* The existing Pharma attendance rules remain unchanged.
* The Excel report/layout remains unchanged.
* employee.extra.shift is NOT used for attendance calculation anymore.

Planning slot:
    planning.slot.resource_id -> employee.resource_id
    planning.slot.start_datetime / end_datetime -> actual assigned shift time
    planning.slot.shift_assigned -> shift type/name

The engine still uses the employee Working Schedule only as a fallback for
week-off detection when there is no Planning slot for that date. This is
important because Planning is being used for shift assignment, not as a
replacement for the employee's weekly calendar/holiday configuration.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
import pytz
from odoo import api, fields, models
from ..lib import attendance_rules as rules


class PharmaAttendanceEngine(models.AbstractModel):
    _name = "pharma.attendance.engine"
    _description = "Pharma Attendance Calculation Engine"

    # ==================================================================
    # PUBLIC API
    # ==================================================================

    @api.model
    def compute_period(self, employees, date_from, date_to):
        """
        Return:
            {
                employee_id: {
                    date: {
                        status,
                        status_kind,
                        first_in,
                        last_out,
                        minutes,
                        shift_name,
                        shift_label,
                        shift_date,
                        is_multi,
                        required_minutes,
                        shift_detail,
                    }
                }
            }

        The report layout consumes this structure directly.
        """
        if date_from > date_to:
            return {}

        today = fields.Date.context_today(self)

        # The first-three-late-entry rule is monthly, so calculate from the
        # first day of the month even when the report starts later.
        calc_from = date_from.replace(day=1)
        calc_days = [
            calc_from + timedelta(days=i) for i in range((date_to - calc_from).days + 1)
        ]

        attendances = self._load_attendances(employees, calc_from, date_to)
        leaves = self._load_leaves(employees, calc_from, date_to)
        holidays = self._load_holidays(calc_from, date_to)

        # Load Planning once for the whole period. This is the key change:
        # no per-cell Planning queries and no employee.extra.shift lookup.
        planning_slots = self._load_planning_slots(
            employees,
            calc_from - timedelta(days=2),
            date_to + timedelta(days=2),
        )

        calendar_cache = {}
        holiday_cache = {}
        result = {}

        for employee in employees:
            tz = self._employee_tz(employee)
            default_calendar = employee.resource_calendar_id or (
                employee.company_id.resource_calendar_id
                if employee.company_id
                else False
            )

            def calendar_info(calendar):
                if not calendar:
                    return None

                key = (calendar.id, tz.zone)
                if key not in calendar_cache:
                    calendar_cache[key] = self._calendar_info(
                        calendar,
                        tz,
                        calc_from - timedelta(days=2),
                        date_to + timedelta(days=2),
                    )
                return calendar_cache[key]

            def planning_for(day):
                return planning_slots.get(employee.id, {}).get(day, [])

            def day_rule(day):
                """
                Return:
                    combined_rule, working, shift_rules

                Priority:
                    1. Employee Working Hours is the primary shift.
                    2. Planning can add extra shifts.
                    3. If Planning contains the same shift as Working Hours,
                    the Working Hours shift is kept and the Planning duplicate
                    is ignored.
                    4. If Employee Working Hours is not selected, Planning is used
                    normally.
                """

                planned = planning_for(day)

                shift_rules = []

                # ==============================================================
                # 1. EMPLOYEE WORKING HOURS
                # ==============================================================

                if employee.resource_calendar_id:
                    info = calendar_info(employee.resource_calendar_id)

                    if info:
                        work_rule, working_dates = info

                        # Working Hours remains the primary/default shift.
                        if day in working_dates:
                            shift_rules.append(work_rule)

                # ==============================================================
                # 2. PLANNING
                #    Planning is allowed to add EXTRA SHIFTS.
                #    But do not duplicate the Working Hours shift.
                # ==============================================================

                for item in planned:
                    planned_rule = item["rule"]

                    duplicate = False

                    for existing_rule in shift_rules:
                        # Same configured shift
                        if existing_rule.key == planned_rule.key or (
                            existing_rule.name
                            and planned_rule.name
                            and existing_rule.name.strip().lower()
                            == planned_rule.name.strip().lower()
                        ):
                            duplicate = True
                            break

                    if not duplicate:
                        shift_rules.append(planned_rule)

                # ==============================================================
                # 3. WE HAVE WORKING HOURS AND/OR PLANNING SHIFTS
                # ==============================================================

                if shift_rules:
                    return (
                        rules.combine_rules(shift_rules),
                        True,
                        shift_rules,
                    )

                # ==============================================================
                # 4. NO WORKING HOURS + NO PLANNING
                #    -> COMPANY WORKING HOURS
                # ==============================================================

                if default_calendar:
                    info = calendar_info(default_calendar)

                    if info:
                        fallback_rule, working_dates = info

                        if day in working_dates:
                            return fallback_rule, True, [fallback_rule]

                        return fallback_rule, False, [fallback_rule]

                # ==============================================================
                # 5. FINAL FALLBACK
                # ==============================================================

                fallback = rules.generic_rule(
                    "Working Hours",
                    9 * 60,
                    18 * 60,
                    8,
                )

                return fallback, day.weekday() < 5, [fallback]

            def rule_for(day):
                return day_rule(day)[0]

            # --------------------------------------------------------------
            # Bucket biometric punches into the correct attendance day.
            # --------------------------------------------------------------
            buckets = defaultdict(list)

            for check_in, check_out in attendances.get(employee.id, ()):
                local_in = self._to_local(check_in, tz)
                local_out = self._to_local(check_out, tz) if check_out else None

                shift_day = self._assign_shift_day(
                    local_in,
                    planning_slots.get(employee.id, {}),
                    rule_for,
                )

                buckets[shift_day].append((local_in, local_out))

            # --------------------------------------------------------------
            # Holiday dates remain based on the employee/company calendar.
            # Planning decides the assigned shift, not public-holiday setup.
            # --------------------------------------------------------------
            hkey = (
                employee.company_id.id if employee.company_id else False,
                default_calendar.id if default_calendar else False,
                tz.zone,
            )

            if hkey not in holiday_cache:
                holiday_cache[hkey] = self._holiday_dates(
                    holidays,
                    employee.company_id,
                    default_calendar,
                    tz,
                    calc_from,
                    date_to,
                )

            holiday_dates = holiday_cache[hkey]
            emp_leaves = leaves.get(employee.id, {})

           
            month_key = None
            emp_result = {}

            for day in calc_days:
                if (day.year, day.month) != month_key:
                    month_key = (day.year, day.month)
                    

                rule, working, day_shifts = day_rule(day)
                planned = planning_for(day)

                # ----------------------------------------------------------
                # Multiple shift detection
                # ----------------------------------------------------------
                # A day is multiple-shift when:
                # 1. More than one shift is planned/configured, OR
                # 2. Imported/manual attendance contains more than one
                #    completed IN -> OUT pair for that day.
                #
                # This ensures that biometric-imported multiple shifts
                # also receive the "Multiple Shifts" Excel comment.
                # ----------------------------------------------------------
                day_punches = buckets.get(day, [])

                completed_pairs = [
                    (check_in, check_out)
                    for check_in, check_out in day_punches
                    if check_in and check_out and check_out > check_in
                ]

                is_multi = len(day_shifts) > 1 or len(completed_pairs) > 1

                # ----------------------------------------------------------
                # Actual worked time
                # ----------------------------------------------------------
                # IMPORTANT: keep the staging calculation exactly as it was:
                # SUM completed IN/OUT pairs, not last_out - first_in.
                # This preserves the client's existing WH calculation.
                pair_limit = max(
                    [rules.pair_limit_minutes(shift_rule) for shift_rule in day_shifts]
                    or [rules.MAX_PAIR_MINUTES]
                )

                summary = rules.summarise_punches(
                    buckets.get(day, []),
                    max_pair_minutes=pair_limit,
                    mode="sum",
                )

                holiday = day in holiday_dates
                is_future = day > today
                if day == today and not summary["has_pair"]:
                    is_future = True

                status, status_kind = rules.evaluate_day_detail(
                    rule,
                    working=working,
                    holiday=holiday,
                    summary=summary,
                    leaves=emp_leaves.get(day, ()),
                    is_future=is_future,
                )

                if day < date_from:
                    continue

                # Planning names and actual windows are kept in the report
                # result. The XLSX layout itself is unchanged.
                if planned:
                    shift_names = [item["name"] for item in planned]
                    shift_detail = " + ".join(
                        rules.window_text(item["rule"]) for item in planned
                    )
                else:
                    shift_names = [shift_rule.name for shift_rule in day_shifts]
                    shift_detail = " + ".join(
                        rules.window_text(shift_rule) for shift_rule in day_shifts
                    )

                # ----------------------------------------------------------
                # Full-day approved leave:
                # Do not expose biometric attendance details in the sheet.
                #
                # The actual hr.attendance records remain untouched.
                # The leave status remains visible.
                # ----------------------------------------------------------
                has_full_day_leave = any(
                    leave.kind == "full" for leave in emp_leaves.get(day, ())
                )

                emp_result[day] = {
                    "status": status,
                    "status_kind": status_kind,
                    # Do not show biometric IN/OUT/WH on a full-day leave.
                    "first_in": None if has_full_day_leave else summary["first_in"],
                    "last_out": None if has_full_day_leave else summary["last_out"],
                    "minutes": None if has_full_day_leave else summary["minutes"],
                    "shift_name": ", ".join(shift_names),
                    "shift_label": rule.label,
                    "is_multi": is_multi,
                    "required_minutes": rule.full_min,
                    "shift_detail": shift_detail,
                    "shift_date": day,
                }

            result[employee.id] = emp_result

        return result

    # ==================================================================
    # PLANNING SOURCE
    # ==================================================================

    def _load_planning_slots(self, employees, date_from, date_to):
        """
        Load Planning assignments once.

        Structure:
            {
                employee_id: {
                    local_start_date: [
                        {
                            'slot': planning.slot,
                            'name': 'General Shift',
                            'rule': ShiftRule(...),
                            'start': local datetime,
                            'end': local datetime,
                            'scheduled_hours': float,
                        },
                    ]
                }
            }

        A night shift 22:00 -> 06:30 is stored under the date on which the
        Planning slot STARTS.
        """
        PlanningSlot = self.env["planning.slot"]
        data = defaultdict(lambda: defaultdict(list))

        resource_ids = employees.mapped("resource_id").ids
        if not resource_ids:
            return data

        # Use a broad UTC window. The final grouping is done in the employee's
        # own timezone, which is what matters for attendance.
        start_utc = datetime.combine(
            date_from - timedelta(days=1),
            time.min,
        )
        end_utc = datetime.combine(
            date_to + timedelta(days=2),
            time.min,
        )

        domain = [
            ("resource_id", "in", resource_ids),
            ("start_datetime", "<", end_utc),
            ("end_datetime", ">", start_utc),
        ]

        # Do NOT restrict to published slots. The user is using Planning as
        # the assignment source and the assigned slot must be respected even
        # while it is still a draft. If a future Odoo version introduces a
        # cancelled state, ignore cancelled slots.
        if "state" in PlanningSlot._fields:
            domain.append(("state", "!=", "cancelled"))

        slots = PlanningSlot.search(
            domain,
            order="resource_id, start_datetime, id",
        )

        employee_by_resource = {
            employee.resource_id.id: employee
            for employee in employees
            if employee.resource_id
        }

        for slot in slots:
            employee = employee_by_resource.get(slot.resource_id.id)
            if not employee:
                continue

            start_local = self._planning_datetime_to_local(
                employee,
                slot.start_datetime,
            )
            end_local = self._planning_datetime_to_local(
                employee,
                slot.end_datetime,
            )

            if not start_local or not end_local or end_local <= start_local:
                continue

            shift_name = self._get_planning_shift_name(slot)
            rule = self._planning_rule_from_slot(
                shift_name,
                start_local,
                end_local,
            )

            if not rule:
                continue

            start_date = start_local.date()
            if start_date < date_from or start_date > date_to:
                # The caller may have asked for calc_from - 2 because an
                # overnight punch needs previous-day context. Keep previous
                # day slots only when they are in the loader's context.
                if start_date < date_from - timedelta(days=1):
                    continue

            data[employee.id][start_date].append(
                {
                    "slot": slot,
                    "name": shift_name or rule.name,
                    "rule": rule,
                    "start": start_local,
                    "end": end_local,
                    "scheduled_hours": (end_local - start_local).total_seconds()
                    / 3600.0,
                }
            )

        for employee_id in data:
            for day in data[employee_id]:
                data[employee_id][day].sort(
                    key=lambda item: (
                        item["start"],
                        item["slot"].id,
                    )
                )

        return data

    def _get_planning_shift_name(self, slot):
        """Shift Assigned is the configured source; slot name is fallback."""
        value = ""

        if "shift_assigned" in slot._fields:
            value = slot.shift_assigned or ""

        if not value and getattr(slot, "template_id", False):
            template = slot.template_id
            if "shift_assigned" in template._fields:
                value = template.shift_assigned or ""

        if not value:
            value = slot.name or ""

        return value.strip()

    def _planning_rule_from_slot(self, shift_name, start_local, end_local):
        """
        Convert an actual Planning slot into the same ShiftRule structure used
        by the existing attendance rules.

        General Shift keeps its special Pharma thresholds:
            PP >= 9h20
            HD >= 4h45

        Every other shift uses the actual Planning slot duration:
            PP >= planned duration
            HD >= half of planned duration
            A < half of planned duration.
        """
        if not start_local or not end_local or end_local <= start_local:
            return None

        text = " ".join((shift_name or "").lower().split())

        if "general" in text:
            key = "general"
            name = shift_name or "General Shift"
            full_min = 9 * 60 + 20
            half_min = 4 * 60 + 45
            is_general = True
        elif "g1" in text or "g-1" in text or "g 1" in text:
            key = "g1"
            name = shift_name or "G1 Shift"
            # Client rule: G1 is 09:30-19:00 = 9h30, HD = 4h45.
            full_min = 9 * 60 + 30
            half_min = 4 * 60 + 45
            is_general = False
        elif "shift a" in text or "shift-a" in text:
            key = "a"
            name = shift_name or "Shift A"
            # Client rule: Shift A = 8h30, HD = 4h15.
            full_min = 8 * 60 + 30
            half_min = 4 * 60 + 15
            is_general = False
        elif "shift b" in text or "shift-b" in text:
            key = "b"
            name = shift_name or "Shift B"
            # Client rule: Shift B = 8h30, HD = 4h15.
            full_min = 8 * 60 + 30
            half_min = 4 * 60 + 15
            is_general = False
        elif "shift c" in text or "shift-c" in text:
            key = "c"
            name = shift_name or "Shift C"
            # Client rule: Shift C = 8h30, HD = 4h15.
            full_min = 8 * 60 + 30
            half_min = 4 * 60 + 15
            is_general = False
        else:
            key = self._planning_shift_key(text)
            name = shift_name or "Planned Shift"
            # Unknown/custom Planning shift: its actual Planning duration is
            # authoritative, with half-day = half of that duration.
            full_min = int((end_local - start_local).total_seconds() // 60)
            half_min = full_min // 2
            is_general = False

        # Minutes since midnight. Overnight end is allowed to exceed 1440.
        start_min = start_local.hour * 60 + start_local.minute
        end_min = end_local.hour * 60 + end_local.minute
        if end_min <= start_min:
            end_min += 1440

        return rules.ShiftRule(
            key,
            name,
            start_min,
            end_min,
            full_min,
            half_min,
            is_general,
        )

    @staticmethod
    def _planning_shift_key(text):
        if "shift a" in text or "shift-a" in text:
            return "a"
        if "shift b" in text or "shift-b" in text:
            return "b"
        if "shift c" in text or "shift-c" in text:
            return "c"
        return "planning"

    def _planning_datetime_to_local(self, employee, value):
        if not value:
            return False

        value = fields.Datetime.to_datetime(value)
        if not value:
            return False

        if value.tzinfo is None:
            value = pytz.UTC.localize(value)
        else:
            value = value.astimezone(pytz.UTC)

        return value.astimezone(self._employee_tz(employee)).replace(tzinfo=None)

    def _assign_shift_day(self, check_in_local, planning_by_day, rule_for):
        """
        Assign a punch to the Planning slot's START date.

        Candidates are the punch's local date and the previous date. This is
        essential for overnight Shift C (22:00 -> 06:30).
        """
        x = check_in_local.date()
        best_day = None
        best_distance = None

        for candidate_day in (x - timedelta(days=1), x):
            planned = planning_by_day.get(candidate_day, [])

            if planned:
                for item in planned:
                    start = item["start"]
                    end = item["end"]
                    if (
                        start - rules.SHIFT_WINDOW_BEFORE
                        <= check_in_local
                        <= end + rules.SHIFT_WINDOW_AFTER
                    ):
                        distance = abs((check_in_local - start).total_seconds())
                        if best_day is None or distance < best_distance:
                            best_day = candidate_day
                            best_distance = distance
                continue

            # No Planning slot for the candidate day. Fall back to the
            # existing calendar rule so old calendar-based attendance data
            # remains correctly bucketed.
            fallback_rule = rule_for(candidate_day)
            if fallback_rule:
                start, end = rules.shift_window(
                    fallback_rule,
                    candidate_day,
                )
                if (
                    start - rules.SHIFT_WINDOW_BEFORE
                    <= check_in_local
                    <= end + rules.SHIFT_WINDOW_AFTER
                ):
                    distance = abs((check_in_local - start).total_seconds())
                    if best_day is None or distance < best_distance:
                        best_day = candidate_day
                        best_distance = distance

        return best_day or x

    # ==================================================================
    # DATA LOADERS
    # ==================================================================

    def _load_attendances(self, employees, date_from, date_to):
        start = datetime.combine(
            date_from - timedelta(days=2),
            time.min,
        )
        end = datetime.combine(
            date_to + timedelta(days=3),
            time.min,
        )

        rows = self.env["hr.attendance"].search_read(
            [
                ("employee_id", "in", employees.ids),
                ("check_in", ">=", start),
                ("check_in", "<", end),
            ],
            [
                "employee_id",
                "check_in",
                "check_out",
            ],
            order="check_in asc, id asc",
        )

        data = defaultdict(list)
        for row in rows:
            employee_value = row.get("employee_id")
            if not employee_value:
                continue

            employee_id = employee_value[0]
            data[employee_id].append(
                (
                    row["check_in"],
                    row["check_out"] or None,
                )
            )

        return data

    def _load_leaves(self, employees, date_from, date_to):
        """Return {employee_id: {date: [LeaveInfo]}}."""
        leaves = self.env["hr.leave"].search(
            [
                ("employee_id", "in", employees.ids),
                ("state", "=", "validate"),
                ("request_date_from", "<=", date_to),
                ("request_date_to", ">=", date_from),
            ]
        )

        data = defaultdict(lambda: defaultdict(list))

        for leave in leaves:
            info = self._leave_info(leave)

            day = max(
                leave.request_date_from,
                date_from,
            )
            last = min(
                leave.request_date_to,
                date_to,
            )

            while day <= last:
                data[leave.employee_id.id][day].append(info)
                day += timedelta(days=1)

        return data

    def _leave_info(self, leave):
        leave_type = leave.holiday_status_id
        abbreviation = (getattr(leave_type, "abbreviation", "") or "").strip()
        code = abbreviation or (leave_type.name or "Leave").strip()

        if rules.is_short_leave(
            leave_type.name,
            abbreviation,
        ):
            return rules.LeaveInfo(
                code,
                "short",
                self._get_leave_minutes(leave),
            )

        if getattr(leave, "request_unit_half", False):
            period = (
                getattr(
                    leave,
                    "request_date_from_period",
                    "",
                )
                or "am"
            )
            kind = "half_pm" if period.lower() in ("pm", "afternoon") else "half_am"
            return rules.LeaveInfo(code, kind)

        if getattr(leave, "request_unit_hours", False):
            try:
                hour = float(
                    getattr(
                        leave,
                        "request_hour_from",
                        0,
                    )
                    or 0
                )
            except (TypeError, ValueError):
                hour = 0.0

            return rules.LeaveInfo(
                code,
                "half_pm" if hour >= 13 else "half_am",
            )

        return rules.LeaveInfo(code, "full")

    @staticmethod
    def _get_leave_minutes(leave):
        """Best-effort duration for registered Short Leave."""
        if hasattr(leave, "number_of_hours_display"):
            try:
                return int(round(float(leave.number_of_hours_display or 0) * 60))
            except (TypeError, ValueError):
                pass

        if hasattr(leave, "number_of_hours"):
            try:
                return int(round(float(leave.number_of_hours or 0) * 60))
            except (TypeError, ValueError):
                pass

        return rules.SHORT_LEAVE_MIN_MINUTES

    def _load_holidays(self, date_from, date_to):
        """All company-wide resource calendar leaves touching the period."""
        start = datetime.combine(
            date_from - timedelta(days=1),
            time.min,
        )
        end = datetime.combine(
            date_to + timedelta(days=2),
            time.min,
        )

        return self.env["resource.calendar.leaves"].search(
            [
                ("resource_id", "=", False),
                ("date_from", "<", end),
                ("date_to", ">", start),
            ]
        )

    def _holiday_dates(
        self,
        holidays,
        company,
        calendar,
        tz,
        date_from,
        date_to,
    ):
        dates = set()

        for holiday in holidays:
            if holiday.company_id and holiday.company_id != company:
                continue

            if holiday.calendar_id and calendar and holiday.calendar_id != calendar:
                continue

            holiday_from = self._to_local(
                holiday.date_from,
                tz,
            ).date()
            holiday_to = self._to_local(
                holiday.date_to - timedelta(seconds=1),
                tz,
            ).date()

            day = max(holiday_from, date_from)
            last = min(holiday_to, date_to)

            while day <= last:
                dates.add(day)
                day += timedelta(days=1)

        return dates

    # ==================================================================
    # CALENDAR FALLBACK
    # ==================================================================

    def _calendar_info(
        self,
        calendar,
        tz,
        date_from,
        date_to,
    ):
        """
        Calendar is retained only for weekly working-day fallback and for
        employees/dates where no Planning slot exists.
        """
        rule = rules.match_rule(calendar.name)

        lines = calendar.attendance_ids.filtered(
            lambda line: not line.display_type and line.day_period != "lunch"
        )

        if rule is None:
            start = int(min(lines.mapped("hour_from") or [9.0]) * 60)
            end = int(max(lines.mapped("hour_to") or [18.0]) * 60)
            rule = rules.generic_rule(
                calendar.name,
                start,
                end,
                getattr(calendar, "hours_per_day", 0.0) or 8.0,
            )

        start_dt = tz.localize(
            datetime.combine(
                date_from,
                time.min,
            )
        )
        end_dt = tz.localize(
            datetime.combine(
                date_to,
                time.min,
            )
        )

        batches = calendar._work_intervals_batch(
            start_dt,
            end_dt,
            compute_leaves=False,
            tz=tz,
        )

        intervals = batches.get(False)
        if intervals is None:
            intervals = next(
                iter(batches.values()),
                [],
            )

        dates = set()

        for item in intervals:
            local_start = item[0].astimezone(tz)

            # Night shifts are represented by an evening interval plus a
            # post-midnight interval. Only the evening interval starts the
            # logical shift day.
            if rule.overnight and local_start.hour < 12:
                continue

            dates.add(local_start.date())

        return rule, dates

    # ==================================================================
    # HELPERS
    # ==================================================================

    @staticmethod
    def _employee_tz(employee):
        name = (
            employee.tz
            or employee.resource_calendar_id.tz
            or employee.company_id.resource_calendar_id.tz
            or "UTC"
        )
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.UTC

    @staticmethod
    def _to_local(value, tz):
        if value.tzinfo is None:
            value = pytz.UTC.localize(value)
        return value.astimezone(tz).replace(tzinfo=None)
