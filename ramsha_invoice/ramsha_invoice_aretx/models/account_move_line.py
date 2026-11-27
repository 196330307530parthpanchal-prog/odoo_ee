from odoo import models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _ramsha_get_size(self):
        """Variant 'Size' attribute value (falls back to all variant values)."""
        self.ensure_one()
        values = self.product_id.product_template_variant_value_ids
        size = values.filtered(lambda v: 'size' in (v.attribute_id.name or '').lower())
        return ', '.join((size or values).mapped('name'))
