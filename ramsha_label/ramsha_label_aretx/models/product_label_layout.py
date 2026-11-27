from odoo import fields, models

ARS_REPORTS = {
    'ars_carpet_2up': 'ramsha_label_aretx.action_report_ars_label_2up',
    'ars_carpet_1up': 'ramsha_label_aretx.action_report_ars_label_1up',
}


class ProductLabelLayout(models.TransientModel):
    _inherit = 'product.label.layout'

    print_format = fields.Selection(
        selection_add=[
            ('ars_carpet_2up', 'Custom label (4x2)'),
            ('ars_carpet_1up', 'Custom label (2x2)'),
        ],
        ondelete={'ars_carpet_2up': 'cascade', 'ars_carpet_1up': 'cascade'},
        default='ars_carpet_2up',
    )

    def _ars_partner_by_product(self):
        """Map product id -> company partner of the receipt the label is printed from."""
        moves = self.env['stock.move']
        if 'move_ids' in self._fields:
            moves = self.move_ids
        if not moves and 'move_line_ids' in self._fields:
            moves = self.move_line_ids.move_id
        ctx = self.env.context
        if not moves and ctx.get('active_model') == 'stock.picking':
            moves = self.env['stock.picking'].browse(ctx.get('active_ids') or []).move_ids
        result = {}
        for move in moves:
            partner = move.picking_id.partner_id
            if partner:
                result[str(move.product_id.id)] = partner.commercial_partner_id.id
        return result

    def _prepare_report_data(self):
        xml_id, data = super()._prepare_report_data()
        if self.print_format in ARS_REPORTS:
            xml_id = ARS_REPORTS[self.print_format]
            data['ars_partner_by_product'] = self._ars_partner_by_product()
            data['ars_pricelist_id'] = self.pricelist_id.id if 'pricelist_id' in self._fields else 0
        return xml_id, data