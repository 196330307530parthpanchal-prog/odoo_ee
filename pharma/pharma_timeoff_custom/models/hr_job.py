from odoo import fields, models

from ..lib import policy


class HrJob(models.Model):
    _inherit = 'hr.job'

    coff_grade = fields.Selection(
        selection=policy.GRADES,
        string='C-Off Level',
        default='below',
        required=True,
        help=(
            'Decides the extra working hours needed to earn '
            'a Compensatory Off:\n'
            '- Sr. Executive & Below: 6h 30m\n'
            '- Above Sr. Executive: 8h 30m'
        ),
    )