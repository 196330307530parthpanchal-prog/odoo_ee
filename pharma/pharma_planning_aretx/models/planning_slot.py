from odoo import fields, models


class PlanningSlot(models.Model):
    _inherit = 'planning.slot'

    shift_assigned = fields.Char(
        string='Shift Assigned',
        related='template_id.shift_assigned',
        readonly=True,
        store=False,
        help='Shift assigned through the selected Planning shift template.',
    )
