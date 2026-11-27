import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
import logging
from ..lib import attendance_rules as rules

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    planning_slot_id = fields.Many2one(
        "planning.slot",
        string="Planned Shift",
        index=True,
        ondelete="set null",
        check_company=True,
        help="Planning shift assigned to this biometric attendance.",
    )

    shift_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Shift",
        ondelete="restrict",
        index=True,
    )

    is_mispunch = fields.Boolean(
        string="Mispunch",
        default=False,
        index=True,
    )

    mispunch_reason = fields.Text(
        string="Mispunch Reason",
    )

    def _cancel_approved_leave_for_attendance(self):
        """
        Cancel an approved leave when the employee has completed
        an attendance record on the same local date.

        The leave is cancelled only when both check-in and check-out
        are available.
        """

        Leave = self.env["hr.leave"]

        for attendance in self:
            if not attendance.employee_id:
                continue

            if not attendance.check_in:
                continue

            if not attendance.check_out:
                continue

            # Zero-duration biometric mispunch attendance must not
            # cancel approved leave.
            if attendance.is_mispunch:
                continue

            # ---------------------------------------------------------
            # Determine the employee's local attendance date.
            # ---------------------------------------------------------
            employee = attendance.employee_id

            timezone_name = (
                    employee.tz
                    or employee.resource_calendar_id.tz
                    or self.env.user.tz
                    or "UTC"
            )

            try:
                timezone = pytz.timezone(timezone_name)
            except pytz.UnknownTimeZoneError:
                timezone = pytz.UTC

            check_in = fields.Datetime.to_datetime(attendance.check_in)

            if check_in.tzinfo is None:
                check_in = pytz.UTC.localize(check_in)
            else:
                check_in = check_in.astimezone(pytz.UTC)

            local_check_in = check_in.astimezone(timezone)

            attendance_date = local_check_in.date()

            # ---------------------------------------------------------
            # Find approved leave for this employee/date.
            # ---------------------------------------------------------
            leaves = Leave.search(
                [
                    ("employee_id", "=", employee.id),
                    ("state", "=", "validate"),
                    ("request_date_from", "<=", attendance_date),
                    ("request_date_to", ">=", attendance_date),
                ]
            )

            for leave in leaves:

                # -----------------------------------------------------
                # Short Leave and half-day / hourly leaves are MEANT to
                # coexist with attendance (the employee works the rest of
                # the day), so they must never be cancelled.  Only a
                # full-day leave on a day the employee actually worked is.
                # -----------------------------------------------------
                leave_type = leave.holiday_status_id
                if rules.is_short_leave(
                        leave_type.name,
                        getattr(leave_type, "abbreviation", ""),
                ):
                    continue
                if getattr(leave, "request_unit_half", False) or getattr(
                        leave, "request_unit_hours", False
                ):
                    continue

                # -----------------------------------------------------
                # Cancel the full-day approved leave.
                # -----------------------------------------------------
                leave._force_cancel(
                    "Employee worked on this date according to biometric attendance.",
                    "mail.mt_note",
                )

        return True

    @api.constrains("check_in", "check_out", "employee_id")
    def _check_validity(self):
        """
        Custom attendance validity for biometric attendances.

        Biometric rules:
        - Multiple OPEN biometric attendances are allowed on different
        local calendar days.
        - Multiple OPEN biometric attendances on the same local day
        are not allowed.
        - Closed attendances cannot overlap.
        - Zero-duration biometric mispunches do not create overlaps.
        - Normal/manual attendance keeps Odoo's standard validation.
        """

        # =============================================================
        # 1. NORMAL / MANUAL ATTENDANCES
        # =============================================================
        # Anything that is not biometric/technical must continue to use
        # Odoo's standard attendance validation.
        # =============================================================

        normal_attendances = self.filtered(
            lambda attendance: attendance.in_mode != "technical"
        )

        if normal_attendances:
            super(
                HrAttendance,
                normal_attendances,
            )._check_validity()

        # =============================================================
        # 2. BIOMETRIC ATTENDANCES
        # =============================================================

        biometric_attendances = self.filtered(
            lambda attendance: attendance.in_mode == "technical"
        )

        Attendance = self.env["hr.attendance"]

        for attendance in biometric_attendances:

            if not attendance.employee_id:
                continue

            if not attendance.check_in:
                continue

            check_in = fields.Datetime.to_datetime(
                attendance.check_in
            )

            check_out = (
                fields.Datetime.to_datetime(
                    attendance.check_out
                )
                if attendance.check_out
                else False
            )

            # =========================================================
            # CHECK-IN / CHECK-OUT ORDER
            # =========================================================

            if check_out and check_out < check_in:
                raise ValidationError(
                    _(
                        "Cannot create attendance record for "
                        "%(employee)s because the checkout time "
                        "is before the check-in time.",
                        employee=attendance.employee_id.name,
                    )
                )

            employee = attendance.employee_id

            # =========================================================
            # EMPLOYEE TIMEZONE
            # =========================================================

            timezone_name = (
                    employee.tz
                    or employee.resource_calendar_id.tz
                    or self.env.user.tz
                    or "UTC"
            )

            try:
                timezone = pytz.timezone(timezone_name)
            except pytz.UnknownTimeZoneError:
                timezone = pytz.UTC

            # =========================================================
            # CURRENT ATTENDANCE LOCAL DATE
            # =========================================================

            if check_in.tzinfo is None:
                check_in_utc = pytz.UTC.localize(check_in)
            else:
                check_in_utc = check_in.astimezone(pytz.UTC)

            current_local_date = (
                check_in_utc.astimezone(timezone).date()
            )

            # =========================================================
            # FIND OTHER ATTENDANCES
            # =========================================================

            other_attendances = Attendance.search(
                [
                    ("employee_id", "=", employee.id),
                    ("id", "!=", attendance.id),
                ]
            )

            for other in other_attendances:

                if not other.check_in:
                    continue

                other_check_in = fields.Datetime.to_datetime(
                    other.check_in
                )

                if other_check_in.tzinfo is None:
                    other_check_in_utc = pytz.UTC.localize(
                        other_check_in
                    )
                else:
                    other_check_in_utc = (
                        other_check_in.astimezone(pytz.UTC)
                    )

                other_local_date = (
                    other_check_in_utc
                    .astimezone(timezone)
                    .date()
                )

                other_check_out = (
                    fields.Datetime.to_datetime(
                        other.check_out
                    )
                    if other.check_out
                    else False
                )

                # =====================================================
                # OTHER ATTENDANCE IS OPEN
                # =====================================================

                if not other_check_out:

                    # -------------------------------------------------
                    # Normal/manual open attendance.
                    #
                    # Preserve Odoo's standard single-open rule.
                    # -------------------------------------------------

                    if other.in_mode != "technical":
                        raise ValidationError(
                            _(
                                "Cannot create new attendance record "
                                "for %(employee)s, the employee hasn't "
                                "checked out since %(datetime)s",
                                employee=employee.name,
                                datetime=other.check_in,
                            )
                        )

                    # -------------------------------------------------
                    # Biometric open attendance.
                    #
                    # SAME LOCAL DAY:
                    #     Not allowed.
                    #
                    # DIFFERENT LOCAL DAY:
                    #     Allowed.
                    #
                    # This allows:
                    #
                    # 28-Oct -> OPEN
                    # 29-Oct -> OPEN
                    #
                    # while preventing:
                    #
                    # 29-Oct 09:00 -> OPEN
                    # 29-Oct 10:00 -> OPEN
                    # -------------------------------------------------

                    if other_local_date == current_local_date:
                        raise ValidationError(
                            _(
                                "Cannot create a second open "
                                "biometric attendance for %(employee)s "
                                "on %(date)s. The employee already has "
                                "an open attendance for this day.",
                                employee=employee.name,
                                date=current_local_date,
                            )
                        )

                    # Different local calendar day.
                    continue

                # =====================================================
                # OTHER ATTENDANCE IS CLOSED
                # =====================================================

                # -----------------------------------------------------
                # Zero-duration attendance.
                #
                # This is our mispunch representation:
                #
                # check_in == check_out
                #
                # It must not be treated as an overlapping attendance.
                # -----------------------------------------------------

                if other_check_out <= other_check_in:
                    continue

                # -----------------------------------------------------
                # Current attendance is OPEN.
                #
                # A closed attendance only conflicts if its interval
                # overlaps the current open attendance.
                # -----------------------------------------------------

                if not check_out:

                    if (
                            other_check_in <= check_in
                            and other_check_out > check_in
                    ):
                        raise ValidationError(
                            _(
                                "Cannot create attendance record for "
                                "%(employee)s because it overlaps with "
                                "another attendance from %(start)s to "
                                "%(end)s.",
                                employee=employee.name,
                                start=other.check_in,
                                end=other.check_out,
                            )
                        )

                    continue

                # -----------------------------------------------------
                # Both attendances are CLOSED.
                #
                # Check whether their actual time intervals overlap.
                # -----------------------------------------------------

                if (
                        other_check_in < check_out
                        and other_check_out > check_in
                ):
                    raise ValidationError(
                        _(
                            "Cannot create attendance record for "
                            "%(employee)s because it overlaps with "
                            "another attendance from %(start)s to "
                            "%(end)s.",
                            employee=employee.name,
                            start=other.check_in,
                            end=other.check_out,
                        )
                    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        Create attendance records.

        Biometric pairing and the 20-hour missed-checkout rule live in
        pharma.biometric.attendance._process_punches_sequentially().
        """

        # Previous-day / historical mispunch handling was removed.
        # Open attendances are now closed by the biometric processor
        # (_process_punches_sequentially) using the 20-hour rule.
        vals_list = [dict(vals) for vals in vals_list]

        # =============================================================
        # 4. CREATE USING ODOO
        # =============================================================

        attendances = super().create(vals_list)

        # =============================================================
        # 5. EXISTING LEAVE CANCELLATION LOGIC
        # =============================================================

        attendances._cancel_approved_leave_for_attendance()

        return attendances

    def write(self, vals):
        result = super().write(vals)

        # Only re-check when attendance timing has changed.
        if "check_in" in vals or "check_out" in vals:
            self._cancel_approved_leave_for_attendance()

        return result

    def action_open_attendance_report_wizard(self):
        """Open the attendance Excel date-range wizard."""
        return {
            "type": "ir.actions.act_window",
            "name": "Generate Attendance Excel",
            "res_model": "pharma.attendance.report.wizard",
            "view_mode": "form",
            "target": "new",
        }