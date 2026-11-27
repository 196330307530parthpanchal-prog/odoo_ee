from odoo import fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    planning_slot_id = fields.Many2one(
        'planning.slot',
        string='Planned Shift',
        index=True,
        ondelete='set null',
        check_company=True,
        help='Planning shift against which this attendance was booked.',
    )

    is_mispunch = fields.Boolean(
        string='Mispunch',
        default=False,
        index=True,
        copy=False,
        help='The attendance was created from an incomplete biometric punch sequence.',
    )

    mispunch_reason = fields.Char(
        string='Mispunch Reason',
        copy=False,
    )
