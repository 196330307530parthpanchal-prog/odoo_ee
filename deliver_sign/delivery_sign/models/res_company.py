from odoo import fields, models

DEFAULT_DELIVERY_SIGN_HTML = """<table class="o_delivery_sign_table" style="width: 80%; margin: 0 auto; border: 1px solid #4a4a4a; border-radius: 12px; border-collapse: separate; border-spacing: 0; table-layout: fixed; page-break-inside: avoid;">
    <tbody>
        <tr style="height: 63px;">
            <td style="width: 28%; height: 63px; vertical-align: bottom; text-align: center; padding: 0 2px 6px 2px; border-right: 1px solid #b0b0b0;">Billing Incharge</td>
            <td style="width: 36%; height: 63px; vertical-align: bottom; text-align: center; padding: 0 2px 6px 2px; border-right: 1px solid #b0b0b0;">Warehouse Incharge</td>
            <td style="width: 36%; height: 63px; vertical-align: bottom; text-align: center; padding: 0 2px 6px 2px;">Dispatch Supervisor</td>
        </tr>
    </tbody>
</table>
"""

class ResCompany(models.Model):
    _inherit = 'res.company'

    delivery_sign_enabled = fields.Boolean(string='Delivery sign', help='Show a signature area at the bottom of the delivery slip.')
    delivery_sign_html = fields.Html(
        string='Delivery sign content',
        default=DEFAULT_DELIVERY_SIGN_HTML,
        translate=True,
        sanitize_attributes=False,
        sanitize_style=True,
    )
