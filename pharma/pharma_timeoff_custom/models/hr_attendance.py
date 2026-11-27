from odoo import _, fields, models
from odoo.exceptions import UserError

from ..lib import policy


class HrAttendance(models.Model):
    """
    Overtime (OT) policy on Odoo's standard overtime approval.

    Odoo lists every attendance with an "Overtime Status"
    (To Approve / Approved / Refused).  Approving it - with the Approve
    button or by changing the status - is checked here:

        1. at least 2:00 of EXTRA working (beyond the regular shift)
        2. before the 15th of the month following the work date
    """
    _inherit = 'hr.attendance'

    def _check_finalized_attendance_period(self):
        # Users in Time Off Constraints group cannot
        # modify attendance belonging to a finalized period.
        if not self.env.user.has_group(
            'pharma_timeoff_custom.group_timeoff_constraints'
        ):
            return

        AttendanceSheet = self.env['pharma.attendance.sheet']

        for attendance in self:
            if not attendance.check_in:
                continue

            attendance_date = fields.Date.context_timestamp(
                attendance,
                attendance.check_in,
            ).date()

            finalized_sheet = AttendanceSheet.search(
                [
                    ('date_from', '<=', attendance_date),
                    ('date_to', '>=', attendance_date),
                    ('state', '=', 'finalized'),
                ],
                limit=1,
            )

            if finalized_sheet:
                raise UserError(
                    _(
                        'You cannot modify attendance records for a '
                        'finalized attendance period.\n\n'
                        'Attendance period: %s to %s.'
                    ) % (
                        finalized_sheet.date_from.strftime('%d/%m/%Y'),
                        finalized_sheet.date_to.strftime('%d/%m/%Y'),
                    )
                )

    def write(self, vals):
        if vals.get('overtime_status') == 'approved':
            self.filtered(
                lambda a: a.overtime_status != 'approved' and a.check_out
            )._check_overtime_policy()

        self._check_finalized_attendance_period()

        return super().write(vals)

    def _check_overtime_policy(self):
        today = fields.Date.context_today(self)
        helper = self.env['pharma.extra.hours']

        for attendance in self:
            figures, work_day = helper.get_figures_for_attendance(attendance)
            employee = attendance.employee_id
            header = _(
                'Overtime cannot be approved for %(employee)s on %(date)s.',
                employee=employee.name,
                date=work_day.strftime('%d/%m/%Y'))

            if not figures['has_attendance']:
                raise UserError(
                    header + '\n\n' + _(
                        'No completed attendance (check-in and check-out) '
                        'was found for that day.'))

            error = policy.eligibility_error(
                'ot', None, figures['extra_minutes'])
            if error:
                raise UserError(
                    header + '\n\n' + error + '\n\n' + _(
                        'Worked: %(worked)s\n'
                        'Regular shift: %(regular)s',
                        worked=policy.hm(figures['worked_minutes']),
                        regular=policy.hm(figures['regular_minutes'])))

            if not policy.is_in_time(work_day, today):
                raise UserError(
                    header + '\n\n' + _(
                        'Overtime must be handled before %(deadline)s '
                        '(the 15th of the following month).',
                        deadline=policy.submission_deadline(
                            work_day).strftime('%d/%m/%Y')))
