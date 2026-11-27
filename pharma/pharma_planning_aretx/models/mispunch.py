from odoo import api, fields, models, _


class PharmaAttendanceMispunch(models.Model):
    _name = 'pharma.attendance.mispunch'
    _description = 'Attendance Mispunch'
    _order = 'punch_datetime desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
    )

    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='cascade',
    )

    planning_slot_id = fields.Many2one(
        'planning.slot',
        string='Planned Shift',
        index=True,
        ondelete='set null',
    )

    punch_datetime = fields.Datetime(
        string='Punch DateTime',
        required=True,
        index=True,
    )

    punch_type = fields.Selection(
        [
            ('missing_out', 'Missing Checkout'),
            ('unmatched', 'Unmatched Punch'),
        ],
        string='Mispunch Type',
        required=True,
        index=True,
    )

    reason = fields.Text(
        string='Reason',
        readonly=True,
    )

    attendance_id = fields.Many2one(
        'hr.attendance',
        string='Resolved Attendance',
        readonly=True,
        ondelete='set null',
    )

    state = fields.Selection(
        [
            ('detected', 'Detected'),
            ('resolved', 'Resolved'),
        ],
        string='Status',
        default='detected',
        required=True,
        index=True,
    )

    company_id = fields.Many2one(
        'res.company',
        related='employee_id.company_id',
        store=True,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.name == _('New'):
                record.name = f'MP/{record.id:06d}'
        return records
