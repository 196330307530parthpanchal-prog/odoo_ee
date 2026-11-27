from datetime import datetime, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import policy


OPEN_STATES = (
    'confirm',
    'validate1',
    'validate',
)


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    # =====================================================================
    # CREATE
    # =====================================================================

    @api.model_create_multi
    def create(self, vals_list):
        leaves = super().create(vals_list)

        leaves._check_coff_credit()

        return leaves

    # =====================================================================
    # APPROVE
    # =====================================================================

    def action_approve(self, check_state=True):
        self._check_coff_credit()

        return super(
            HrLeave,
            self.with_context(
                pharma_coff_checked=True
            )
        ).action_approve(
            check_state=check_state
        )

    # =====================================================================
    # VALIDATE
    # =====================================================================

    def action_validate(self, check_state=True):
        self._check_coff_credit()

        return super(
            HrLeave,
            self.with_context(
                pharma_coff_checked=True
            )
        ).action_validate(
            check_state=check_state
        )

    # =====================================================================
    # C-OFF ELIGIBILITY
    # =====================================================================

    def _check_coff_credit(self):
        """
        Validate Compensatory Off according to client policy.

        Client policy:

            Sr. Executive & Below:
                Minimum 6 hours 30 minutes EXTRA working.

            Above Sr. Executive:
                Minimum 8 hours 30 minutes EXTRA working.

            Maximum:
                2 C-Offs can be availed in one calendar month.

        IMPORTANT:

            C-Off eligibility currently uses Odoo's native
            hr.attendance model.

            The native Odoo field:

                validated_overtime_hours

            is used as the source of validated EXTRA working hours.

        An Extra Shift record is NOT required.

        A normal General Shift employee can earn C-Off by
        working beyond the regular schedule.
        """

        # Prevent duplicate validation when Odoo's workflow
        # calls another method with the same context.
        if self.env.context.get('pharma_coff_checked'):
            return

        Attendance = self.env['hr.attendance'].sudo()

        for leave in self:

            # -------------------------------------------------------------
            # BASIC CHECKS
            # -------------------------------------------------------------

            if (
                leave.state in ('refuse', 'cancel')
                or not leave.employee_id
                or not leave.holiday_status_id
            ):
                continue

            # -------------------------------------------------------------
            # ONLY C-OFF
            # -------------------------------------------------------------

            if self._get_policy_leave_code(
                leave.holiday_status_id
            ) != 'C-OFF':
                continue

            employee = leave.employee_id.sudo()

            # -------------------------------------------------------------
            # EMPLOYEE MUST HAVE JOB POSITION
            # -------------------------------------------------------------

            if not employee.job_id:
                raise UserError(
                    _(
                        'C-Off cannot be approved for %(employee)s.\n\n'
                        'Please assign a Job Position to the employee '
                        'before applying for Compensatory Off.'
                    ) % {
                        'employee': employee.name,
                    }
                )

            # -------------------------------------------------------------
            # DETERMINE C-OFF LEVEL FROM JOB POSITION
            # -------------------------------------------------------------

            grade = (
                employee.job_id.coff_grade
                or 'below'
            )

            required_extra_minutes = policy.min_extra_minutes(
                'coff',
                grade,
            )

            # -------------------------------------------------------------
            # REQUESTED C-OFF DATES
            # -------------------------------------------------------------

            start_date = leave.request_date_from

            end_date = (
                leave.request_date_to
                or start_date
            )

            if not start_date:
                continue

            # -------------------------------------------------------------
            # MONTHLY C-OFF LIMIT
            #
            # Maximum 2 C-Offs can be availed in one calendar month.
            #
            # Preserve the existing behavior:
            # existing C-Off records are counted as records, while
            # the current request is counted by requested days.
            # -------------------------------------------------------------

            month_start = start_date.replace(
                day=1
            )

            if start_date.month == 12:
                month_end = start_date.replace(
                    year=start_date.year + 1,
                    month=1,
                    day=1,
                )
            else:
                month_end = start_date.replace(
                    month=start_date.month + 1,
                    day=1,
                )

            existing_coffs = self.search([
                ('id', 'not in', self.ids),
                ('employee_id', '=', employee.id),
                ('state', 'in', OPEN_STATES),
                ('request_date_from', '>=', month_start),
                ('request_date_from', '<', month_end),
            ])

            existing_coff_count = 0

            for existing in existing_coffs:
                if (
                    self._get_policy_leave_code(
                        existing.holiday_status_id
                    ) == 'C-OFF'
                ):
                    existing_coff_count += 1

            requested_days = (
                (end_date - start_date).days + 1
            )

            monthly_limit = policy.coff_monthly_limit()

            if (
                existing_coff_count + requested_days
                > monthly_limit
            ):
                raise UserError(
                    _(
                        'C-Off cannot be approved for %(employee)s.\n\n'
                        'C-Off limit for the month: %(limit)s\n'
                        'Already requested/approved: %(existing)s\n'
                        'Requested now: %(requested)s\n\n'
                        'Only %(limit)s C-Off(s) can be availed '
                        'in a calendar month.'
                    ) % {
                        'employee': employee.name,
                        'limit': monthly_limit,
                        'existing': existing_coff_count,
                        'requested': requested_days,
                    }
                )

            # -------------------------------------------------------------
            # CHECK EACH C-OFF DATE
            #
            # We now use Odoo's native hr.attendance records.
            #
            # We DO NOT use:
            #
            #     pharma.attendance.engine.compute_period()
            #
            # for C-Off eligibility.
            # -------------------------------------------------------------

            current_date = start_date

            while current_date <= end_date:

                # ---------------------------------------------------------
                # EMPLOYEE TIMEZONE
                # ---------------------------------------------------------

                timezone_name = (
                    employee.tz
                    or (
                        employee.resource_calendar_id.tz
                        if employee.resource_calendar_id
                        else False
                    )
                    or self.env.user.tz
                    or 'UTC'
                )

                timezone = pytz.timezone(
                    timezone_name
                )

                # ---------------------------------------------------------
                # LOCAL DAY START
                # ---------------------------------------------------------

                local_start = timezone.localize(
                    datetime.combine(
                        current_date,
                        datetime.min.time(),
                    )
                )

                # ---------------------------------------------------------
                # LOCAL NEXT DAY START
                # ---------------------------------------------------------

                local_end = timezone.localize(
                    datetime.combine(
                        current_date + timedelta(days=1),
                        datetime.min.time(),
                    )
                )

                # ---------------------------------------------------------
                # CONVERT LOCAL DAY TO UTC
                #
                # Odoo stores attendance datetimes in UTC.
                # ---------------------------------------------------------

                utc_start = (
                    local_start
                    .astimezone(pytz.UTC)
                    .replace(tzinfo=None)
                )

                utc_end = (
                    local_end
                    .astimezone(pytz.UTC)
                    .replace(tzinfo=None)
                )

                utc_start_string = fields.Datetime.to_string(
                    utc_start
                )

                utc_end_string = fields.Datetime.to_string(
                    utc_end
                )

                # ---------------------------------------------------------
                # FIND ATTENDANCES OVERLAPPING THIS EMPLOYEE-LOCAL DAY
                #
                # This also handles overnight attendance records.
                #
                # Example:
                #
                #   06/10 22:00 -> 07/10 06:30
                #
                # The attendance overlaps both dates.
                # ---------------------------------------------------------

                attendances = Attendance.search([
                    ('employee_id', '=', employee.id),
                    ('check_in', '<', utc_end_string),
                    ('check_out', '!=', False),
                    ('check_out', '>', utc_start_string),
                ], order='check_in asc')

                # ---------------------------------------------------------
                # NO COMPLETED ATTENDANCE
                # ---------------------------------------------------------

                if not attendances:
                    raise UserError(
                        _(
                            'C-Off cannot be approved for '
                            '%(employee)s on %(date)s.\n\n'
                            'No completed attendance record was found '
                            'for this date.'
                        ) % {
                            'employee': employee.name,
                            'date': current_date.strftime(
                                '%d/%m/%Y'
                            ),
                        }
                    )

                # ---------------------------------------------------------
                # READ ODOO'S NATIVE ATTENDANCE VALUES
                # ---------------------------------------------------------

                worked_minutes = 0
                extra_working_minutes = 0

                for attendance in attendances:

                    # -----------------------------------------------------
                    # WORKED HOURS
                    #
                    # Odoo stores worked_hours as decimal hours.
                    #
                    # Example:
                    #
                    #   17.0 -> 1020 minutes -> 17:00
                    # -----------------------------------------------------

                    worked_hours = float(
                        attendance.worked_hours or 0.0
                    )

                    worked_minutes += int(
                        round(
                            worked_hours * 60
                        )
                    )

                    # -----------------------------------------------------
                    # VALIDATED EXTRA HOURS
                    #
                    # Odoo's native field:
                    #
                    #   validated_overtime_hours
                    #
                    # Example:
                    #
                    #   7.5 -> 450 minutes -> 07:30
                    #
                    # Negative extra hours do not contribute to C-Off.
                    # -----------------------------------------------------

                    validated_overtime_hours = float(
                        attendance.validated_overtime_hours
                        or 0.0
                    )

                    validated_overtime_hours = max(
                        0.0,
                        validated_overtime_hours,
                    )

                    extra_working_minutes += int(
                        round(
                            validated_overtime_hours * 60
                        )
                    )

                # ---------------------------------------------------------
                # C-OFF ELIGIBILITY
                # ---------------------------------------------------------

                if (
                    extra_working_minutes
                    < required_extra_minutes
                ):

                    grade_label = dict(
                        policy.GRADES
                    ).get(
                        grade,
                        'Sr. Executive & Below',
                    )

                    raise UserError(
                        _(
                            'C-Off cannot be approved for '
                            '%(employee)s.\n\n'
                            'Date: %(date)s\n'
                            'C-Off Level: %(grade)s\n\n'
                            'Required extra working: %(required)s\n'
                            'Actual extra working: %(actual)s\n\n'
                            'Worked: %(worked)s\n\n'
                            'C-Off eligibility has not been met.'
                        ) % {
                            'employee': employee.name,
                            'date': current_date.strftime(
                                '%d/%m/%Y'
                            ),
                            'grade': grade_label,
                            'required': policy.hm(
                                required_extra_minutes
                            ),
                            'actual': policy.hm(
                                extra_working_minutes
                            ),
                            'worked': policy.hm(
                                worked_minutes
                            ),
                        }
                    )

                # ---------------------------------------------------------
                # NEXT DATE
                # ---------------------------------------------------------

                current_date += timedelta(days=1)