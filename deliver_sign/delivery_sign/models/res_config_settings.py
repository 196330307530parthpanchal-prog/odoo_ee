from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    delivery_sign_enabled = fields.Boolean(
        string='Delivery sign',
        related='company_id.delivery_sign_enabled', readonly=False)
    delivery_sign_html = fields.Html(
        string='Delivery sign content',
        related='company_id.delivery_sign_html', readonly=False)
