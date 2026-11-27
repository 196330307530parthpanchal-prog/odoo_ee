from datetime import datetime, timedelta

import logging
import pytz

from odoo import api, fields, models


_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    biometric_user_id = fields.Char(
        string="Biometric User ID",
        help="Must match the User ID stored in the biometric device.",
    )

    last_absent_reminder_date = fields.Date(
        string="Last Absent Reminder Date",
        readonly=True,
        copy=False,
    )

    @api.model
    def cron_send_absent_reminders(self):
        """
        Check the previous day for employees who were expected to work
        but have no attendance and no leave, then send an email reminder.
        """

        _logger.warning("🚀 ABSENT REMINDER METHOD STARTED")

        # ---------------------------------------------------------
        # DETERMINE PREVIOUS DAY
        # ---------------------------------------------------------
        company = self.env.company

        timezone_name = (
            company.partner_id.tz
            or self.env.user.tz
            or "UTC"
        )

        timezone = pytz.timezone(timezone_name)

        current_datetime = datetime.now(timezone)
        absent_date = current_datetime.date() - timedelta(days=1)

        _logger.warning(
            "📅 ABSENT REMINDER CHECKING DATE: %s",
            absent_date,
        )

        _logger.warning(
            "🌍 COMPANY TIMEZONE: %s",
            timezone_name,
        )

        # ---------------------------------------------------------
        # GET EMAIL TEMPLATE
        # ---------------------------------------------------------
        template = self.env.ref(
            "pharma_bioattendance_aretx.email_template_absent_reminder",
            raise_if_not_found=False,
        )

        if not template:
            _logger.error(
                "❌ ABSENT REMINDER EMAIL TEMPLATE NOT FOUND"
            )
            return

        _logger.warning(
            "📧 ABSENT REMINDER EMAIL TEMPLATE FOUND: %s",
            template.name,
        )

        # ---------------------------------------------------------
        # GET ACTIVE EMPLOYEES WITH EMAIL
        # ---------------------------------------------------------
        employees = self.search([
            ("active", "=", True),
            ("work_email", "!=", False),
        ])

        _logger.warning(
            "👥 ABSENT REMINDER EMPLOYEES FOUND: %s",
            len(employees),
        )

        # ---------------------------------------------------------
        # PROCESS EACH EMPLOYEE
        # ---------------------------------------------------------
        for employee in employees:

            _logger.warning(
                "🔍 CHECKING EMPLOYEE: %s | ID: %s | EMAIL: %s",
                employee.name,
                employee.id,
                employee.work_email,
            )

            # -----------------------------------------------------
            # GET EMPLOYEE WORKING CALENDAR
            # -----------------------------------------------------
            calendar = employee.resource_calendar_id

            if not calendar:
                _logger.warning(
                    "⏭️ SKIPPING %s: NO WORKING CALENDAR",
                    employee.name,
                )
                continue

            _logger.warning(
                "📆 EMPLOYEE CALENDAR: %s | ID: %s",
                calendar.name,
                calendar.id,
            )

            # -----------------------------------------------------
            # CHECK WHETHER EMPLOYEE WAS SCHEDULED TO WORK
            # -----------------------------------------------------
            weekday = str(absent_date.weekday())

            _logger.warning(
                "📅 CHECKING WORKING DAY: %s | WEEKDAY CODE: %s",
                absent_date,
                weekday,
            )

            working_day = calendar.attendance_ids.filtered(
                lambda attendance:
                    attendance.dayofweek == weekday
            )

            if not working_day:
                _logger.warning(
                    "⏭️ SKIPPING %s: NOT A SCHEDULED WORKING DAY",
                    employee.name,
                )
                continue

            _logger.warning(
                "✅ %s WAS SCHEDULED TO WORK ON %s",
                employee.name,
                absent_date,
            )

            # -----------------------------------------------------
            # CALCULATE UTC DATE RANGE
            # -----------------------------------------------------
            day_start_utc = timezone.localize(
                datetime.combine(
                    absent_date,
                    datetime.min.time(),
                )
            ).astimezone(pytz.UTC).replace(tzinfo=None)

            day_end_utc = timezone.localize(
                datetime.combine(
                    absent_date + timedelta(days=1),
                    datetime.min.time(),
                )
            ).astimezone(pytz.UTC).replace(tzinfo=None)

            _logger.warning(
                "🕐 DATE RANGE FOR %s: %s → %s UTC",
                employee.name,
                day_start_utc,
                day_end_utc,
            )

            # -----------------------------------------------------
            # CHECK COMPANY CALENDAR LEAVE / HOLIDAY
            # -----------------------------------------------------
            calendar_leave = self.env["resource.calendar.leaves"].search([
                ("calendar_id", "=", calendar.id),
                ("date_from", "<", day_end_utc),
                ("date_to", ">=", day_start_utc),
            ], limit=1)

            if calendar_leave:
                _logger.warning(
                    "⏭️ SKIPPING %s: COMPANY CALENDAR LEAVE/HOLIDAY FOUND | LEAVE ID: %s",
                    employee.name,
                    calendar_leave.id,
                )
                continue

            _logger.warning(
                "✅ NO COMPANY HOLIDAY FOUND FOR %s",
                employee.name,
            )

            # -----------------------------------------------------
            # CHECK ATTENDANCE
            # -----------------------------------------------------
            attendance = self.env["hr.attendance"].search([
                ("employee_id", "=", employee.id),
                ("check_in", ">=", day_start_utc),
                ("check_in", "<", day_end_utc),
            ], limit=1)

            if attendance:
                _logger.warning(
                    "⏭️ SKIPPING %s: ATTENDANCE FOUND | ATTENDANCE ID: %s | CHECK-IN: %s",
                    employee.name,
                    attendance.id,
                    attendance.check_in,
                )
                continue

            _logger.warning(
                "❌ NO ATTENDANCE FOUND FOR %s ON %s",
                employee.name,
                absent_date,
            )

            # -----------------------------------------------------
            # CHECK LEAVE
            # -----------------------------------------------------
            leave = self.env["hr.leave"].search([
                ("employee_id", "=", employee.id),
                ("state", "in", [
                    "confirm",
                    "validate1",
                    "validate",
                ]),
                ("date_from", "<", day_end_utc),
                ("date_to", ">=", day_start_utc),
            ], limit=1)

            if leave:
                _logger.warning(
                    "⏭️ SKIPPING %s: LEAVE FOUND | LEAVE ID: %s | STATE: %s",
                    employee.name,
                    leave.id,
                    leave.state,
                )
                continue

            _logger.warning(
                "❌ NO LEAVE FOUND FOR %s ON %s",
                employee.name,
                absent_date,
            )

            # -----------------------------------------------------
            # PREVENT DUPLICATE EMAIL
            # -----------------------------------------------------
            if employee.last_absent_reminder_date == absent_date:
                _logger.warning(
                    "⏭️ SKIPPING %s: ABSENT REMINDER ALREADY SENT FOR %s",
                    employee.name,
                    absent_date,
                )
                continue

            _logger.warning(
                "🚨 ABSENT EMPLOYEE FOUND: %s | DATE: %s | SENDING EMAIL",
                employee.name,
                absent_date,
            )

            # -----------------------------------------------------
            # SEND EMAIL
            # -----------------------------------------------------
            try:
                template.with_context(
                    absent_date=absent_date.strftime("%d-%m-%Y"),
                ).send_mail(
                    employee.id,
                    force_send=True,
                )

                _logger.warning(
                    "📧 ABSENT REMINDER EMAIL REQUESTED FOR: %s | EMAIL: %s",
                    employee.name,
                    employee.work_email,
                )

            except Exception:
                _logger.exception(
                    "❌ FAILED TO SEND ABSENT REMINDER EMAIL FOR: %s | EMAIL: %s",
                    employee.name,
                    employee.work_email,
                )
                continue

            # -----------------------------------------------------
            # MARK REMINDER AS SENT
            # -----------------------------------------------------
            employee.last_absent_reminder_date = absent_date

            _logger.warning(
                "✅ ABSENT REMINDER MARKED AS SENT FOR: %s | DATE: %s",
                employee.name,
                absent_date,
            )

        _logger.warning(
            "🏁 ABSENT REMINDER METHOD COMPLETED"
        )
