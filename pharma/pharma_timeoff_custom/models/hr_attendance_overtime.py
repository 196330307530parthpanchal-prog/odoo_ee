from odoo import api, fields, models


class HrAttendanceOvertime(models.Model):
    _inherit = 'hr.attendance.overtime'

    pharma_extra_minutes = fields.Integer(
        string='Extra Working Minutes',
        compute='_compute_pharma_extra_minutes',
        store=False,
    )

    pharma_ot_eligible = fields.Boolean(
        string='OT Eligible',
        compute='_compute_pharma_eligibility',
        store=False,
    )

    pharma_coff_eligible = fields.Boolean(
        string='C-Off Eligible',
        compute='_compute_pharma_eligibility',
        store=False,
    )

    @api.depends('duration')
    def _compute_pharma_extra_minutes(self):
        for overtime in self:
            overtime.pharma_extra_minutes = int(
                round((overtime.duration or 0.0) * 60)
            )

    @api.depends(
        'duration',
        'employee_id',
        'employee_id.job_id',
        'employee_id.job_id.coff_grade',
    )
    def _compute_pharma_eligibility(self):
        for overtime in self:
            extra_minutes = int(
                round((overtime.duration or 0.0) * 60)
            )

            overtime.pharma_ot_eligible = (
                extra_minutes >= 120
            )

            grade = (
                overtime.employee_id.job_id.coff_grade
                if overtime.employee_id
                and overtime.employee_id.job_id
                else 'below'
            )

            coff_required = (
                390
                if grade == 'below'
                else 510
            )

            overtime.pharma_coff_eligible = (
                extra_minutes >= coff_required
            )