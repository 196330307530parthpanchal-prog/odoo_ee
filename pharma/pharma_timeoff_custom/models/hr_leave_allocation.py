from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..lib import policy

WATCHED_FIELDS = {'holiday_status_id', 'employee_id', 'coff_work_date'}


class HrLeaveAllocation(models.Model):
    """
    Compensatory Off (C-Off) policy on Odoo's standard Time Off allocation.

    A C-Off allocation is the credit an employee earns by working extra.
    The person creating it states the DATE the extra work was done; the
    allocation is refused with a clear message when that employee did not
    work enough extra hours that day:

        Sr. Executive & Below  -> at least 6:30 of extra working
        Above Sr. Executive    -> at least 8:30 of extra working

    "Extra" means beyond the regular shift hours (week-offs and holidays
    count in full).  The level comes from the Job Position's C-Off Level.
    """
    _inherit = 'hr.leave.allocation'

    coff_work_date = fields.Date(
        string='Extra Work Done On', copy=False, tracking=True,
        help='The day the employee worked extra hours to earn this '
             'Compensatory Off.')
    is_coff_allocation = fields.Boolean(
        compute='_compute_is_coff_allocation')

    @api.depends('holiday_status_id')
    def _compute_is_coff_allocation(self):
        Leave = self.env['hr.leave']
        for allocation in self:
            allocation.is_coff_allocation = bool(
                allocation.holiday_status_id
                and Leave._get_policy_leave_code(
                    allocation.holiday_status_id) == 'C-OFF')

    # ------------------------------------------------------------------
    # WHEN THE CHECK RUNS
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        allocations = super().create(vals_list)
        allocations._check_coff_policy()
        return allocations

    def write(self, vals):
        result = super().write(vals)
        if WATCHED_FIELDS & set(vals):
            self._check_coff_policy()
        return result

    def action_approve(self):
        self._check_coff_policy()
        return super().action_approve()

    def action_validate(self):
        self._check_coff_policy()
        return super().action_validate()

    # ------------------------------------------------------------------
    # IS THIS ALLOCATION BACKED BY REAL EXTRA WORK?  (used when a C-Off
    # Time Off request is created / approved)
    # ------------------------------------------------------------------
    def _coff_eligibility_problem(self):
        """'' when this allocation is backed by a date on which the employee
        really worked enough extra hours; otherwise the reason."""
        self.ensure_one()
        employee, work_date = self.employee_id, self.coff_work_date
        if not work_date:
            return _('no "Extra Work Done On" date')
        if work_date >= fields.Date.context_today(self):
            return _('the work date is not a completed day')
        if not employee.job_id:
            return _('the employee has no Job Position')
        figures = self.env['pharma.extra.hours'].get_figures(
            employee, work_date)
        if not figures['has_attendance']:
            return _('no completed attendance on %s',
                     work_date.strftime('%d/%m/%Y'))
        error = policy.eligibility_error(
            'coff', employee.job_id.coff_grade or 'below',
            figures['extra_minutes'])
        if error:
            return _('not enough extra working on %s',
                     work_date.strftime('%d/%m/%Y'))
        return ''

    # ------------------------------------------------------------------
    # THE CHECK
    # ------------------------------------------------------------------
    def _check_coff_policy(self):
        today = fields.Date.context_today(self)
        helper = self.env['pharma.extra.hours']

        for allocation in self:
            if allocation.state == 'refuse' or not allocation.is_coff_allocation:
                continue

            employee = allocation.employee_id
            work_date = allocation.coff_work_date

            if not work_date:
                raise UserError(_(
                    'Select the date on which %s worked extra hours '
                    '("Extra Work Done On") for this Compensatory Off.',
                    employee.name))

            date_text = work_date.strftime('%d/%m/%Y')
            header = _(
                'Compensatory Off cannot be given to %(employee)s for '
                '%(date)s.', employee=employee.name, date=date_text)

            if work_date >= today:
                raise UserError(header + '\n\n' + _(
                    'The extra work must be on a completed day (before '
                    'today).'))

            if not employee.job_id:
                raise UserError(header + '\n\n' + _(
                    'Set a Job Position on the employee first. Its C-Off '
                    'Level decides how many extra hours are needed.'))

            duplicate = self.sudo().search([
                ('id', '!=', allocation.id),
                ('employee_id', '=', employee.id),
                ('holiday_status_id', '=', allocation.holiday_status_id.id),
                ('coff_work_date', '=', work_date),
                ('state', '!=', 'refuse'),
            ], limit=1)
            if duplicate:
                raise UserError(header + '\n\n' + _(
                    'A Compensatory Off has already been given for that '
                    'date.'))

            figures = helper.get_figures(employee, work_date)
            if not figures['has_attendance']:
                raise UserError(header + '\n\n' + _(
                    'No completed attendance (check-in and check-out) '
                    'was found for that day.'))

            error = policy.eligibility_error(
                'coff', employee.job_id.coff_grade or 'below',
                figures['extra_minutes'])
            if error:
                level = dict(policy.GRADES).get(
                    employee.job_id.coff_grade or 'below')
                raise UserError(header + '\n\n' + error + '\n\n' + _(
                    'Level: %(level)s\n'
                    'Worked: %(worked)s\n'
                    'Regular shift: %(regular)s',
                    level=level,
                    worked=policy.hm(figures['worked_minutes']),
                    regular=policy.hm(figures['regular_minutes'])))
