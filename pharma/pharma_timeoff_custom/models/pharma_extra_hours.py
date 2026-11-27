from datetime import timedelta

import pytz

from odoo import _, api, models
from odoo.exceptions import UserError

from ..lib import policy


class PharmaExtraHours(models.AbstractModel):
    """
    Single place that answers: "how many EXTRA hours did this employee work
    on this day?"  It uses the same engine that builds the attendance sheet,
    so shifts (General / A / B / C / G1), Extra Shifts, week-offs and public
    holidays are all handled exactly as on the sheet.

        extra working = worked - regular shift length
        (week-off / holiday: regular shift length is 0, so all of it is extra)
    """
    _name = 'pharma.extra.hours'
    _description = 'Extra working hours (beyond the regular shift)'

    @api.model
    def get_figures(self, employee, day):
        """Return a dict for the employee-day:
        has_attendance, worked_minutes, regular_minutes, extra_minutes,
        first_in, last_out (employee-local naive datetimes)."""
        engine = self.env['pharma.attendance.engine'].sudo()
        result = engine.compute_period(employee.sudo(), day, day)
        return self._figures(result.get(employee.id, {}).get(day))

    @api.model
    def get_figures_for_attendance(self, attendance):
        """Figures for the shift-day an attendance record belongs to
        (a night shift that started yesterday belongs to yesterday).
        Returns (figures, shift_day)."""
        employee = attendance.employee_id
        tz = pytz.timezone(
            employee.tz
            or (employee.resource_calendar_id.tz
                if employee.resource_calendar_id else False)
            or 'UTC')
        local_in = pytz.UTC.localize(attendance.check_in).astimezone(
            tz).replace(tzinfo=None)
        calendar_day = local_in.date()

        engine = self.env['pharma.attendance.engine'].sudo()
        result = engine.compute_period(
            employee.sudo(), calendar_day - timedelta(days=1), calendar_day
        ).get(employee.id, {})

        for day in (calendar_day, calendar_day - timedelta(days=1)):
            info = result.get(day)
            if (info and info.get('first_in') and info.get('last_out')
                    and info['first_in'] <= local_in <= info['last_out']):
                return self._figures(info), day
        return self._figures(result.get(calendar_day)), calendar_day

    @api.model
    def _figures(self, info):
        empty = {'has_attendance': False, 'worked_minutes': 0,
                 'regular_minutes': 0, 'extra_minutes': 0,
                 'first_in': False, 'last_out': False}
        if not info or info.get('minutes') is None:
            return empty
        if 'regular_required_minutes' not in info:
            raise UserError(_(
                'The attendance engine is out of date (it does not report '
                'the regular shift hours). Update pharma_bioattendance_aretx '
                'and restart Odoo.'))
        worked = info['minutes']
        regular = info['regular_required_minutes'] or 0
        return {
            'has_attendance': True,
            'worked_minutes': worked,
            'regular_minutes': regular,
            'extra_minutes': policy.extra_minutes(worked, regular),
            'first_in': info.get('first_in'),
            'last_out': info.get('last_out'),
        }
