from odoo.tests import tagged
from odoo.addons.base.tests.common import BaseCommon


@tagged('post_install', '-at_install')
class TestDeliverySign(BaseCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.product = cls.env['product.product'].create({'name': 'Sign Product', 'is_storable': True})
        cls.partner = cls.env['res.partner'].create({'name': 'Sign Customer'})
        wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        customers = cls.env.ref('stock.stock_location_customers')
        cls.picking = cls.env['stock.picking'].create({
            'partner_id': cls.partner.id,
            'picking_type_id': wh.out_type_id.id,
            'location_id': wh.lot_stock_id.id,
            'location_dest_id': customers.id,
            'move_ids': [(0, 0, {
                'product_id': cls.product.id,
                'product_uom_qty': 1,
                'location_id': wh.lot_stock_id.id,
                'location_dest_id': customers.id,
            })],
        })

    def _render(self):
        html, _ = self.env['ir.actions.report']._render_qweb_html(
            'stock.report_deliveryslip', self.picking.ids)
        return html.decode()

    def test_settings_save_and_restore(self):
        custom = '<table><tbody><tr><td>Custom Sign A</td><td>Custom Sign B</td></tr></tbody></table>'
        settings = self.env['res.config.settings'].create({
            'delivery_sign_enabled': True,
            'delivery_sign_html': custom,
        })
        settings.execute()
        self.assertTrue(self.company.delivery_sign_enabled)
        self.assertIn('Custom Sign A', self.company.delivery_sign_html)

        reopened = self.env['res.config.settings'].create({})
        self.assertTrue(reopened.delivery_sign_enabled)
        self.assertIn('Custom Sign B', reopened.delivery_sign_html)

        reopened.delivery_sign_enabled = False
        reopened.execute()
        self.assertFalse(self.company.delivery_sign_enabled)

    def test_company_specific(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.company.delivery_sign_enabled = True
        self.assertFalse(other.delivery_sign_enabled)

    def test_report_enabled(self):
        self.company.delivery_sign_enabled = True
        html = self._render()
        for label in ('Billing Incharge', 'Warehouse Incharge', 'Dispatch Supervisor'):
            self.assertIn(label, html)

    def test_report_disabled(self):
        self.company.delivery_sign_enabled = False
        html = self._render()
        self.assertNotIn('Billing Incharge', html)
        self.assertNotIn('o_delivery_sign', html)
