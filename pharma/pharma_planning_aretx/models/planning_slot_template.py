from odoo import fields, models


class PlanningSlotTemplate(models.Model):
    _inherit = 'planning.slot.template'

    shift_assigned = fields.Char(
        string='Shift Assigned',
        help=(
            'Shift name used by the Pharma attendance engine. '
            'The value must match one of the configured attendance shift '
            'names, such as Shift A, Shift B, Shift C, General Shift or G1 Shift.'
        ),
    )
