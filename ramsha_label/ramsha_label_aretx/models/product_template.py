from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    label_size = fields.Char(
        string='Label Size',
        help='Text printed after "SIZE:" on the ARS label, e.g. 200 CM RD. '
             'If empty, a product attribute named "Size" is used.',
    )
