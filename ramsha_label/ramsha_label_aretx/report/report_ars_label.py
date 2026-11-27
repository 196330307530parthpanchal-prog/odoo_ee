import base64
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ReportArsLabelMixin(models.AbstractModel):
    _name = 'report.ramsha_label_aretx.mixin'
    _description = 'ARS Label Report Mixin'

    def _ars_per_row(self):
        return 2

    @staticmethod
    def _ars_qty(value):
        if isinstance(value, (list, tuple)):
            total = 0
            for item in value:
                total += int(item[1] if isinstance(item, (list, tuple)) else item)
            return total
        return int(value or 0)

    def _ars_barcode_img(self, value):
        """Barcode as an embedded PNG, so the PDF engine needs no HTTP request."""
        if not value:
            return ''
        try:
            png = self.env['ir.actions.report'].barcode(
                'Code128', value, width=600, height=150, humanreadable=0)
            return 'data:image/png;base64,%s' % base64.b64encode(png).decode()
        except Exception:
            _logger.exception('Could not generate barcode for %r', value)
            return ''

    def _ars_label_vals(self, product, partner=None, pricelist=None):
        company = product.company_id or self.env.company
        if pricelist:
            # Price and currency follow the pricelist chosen in the Print Labels wizard
            currency = pricelist.currency_id
            try:
                price = pricelist._get_product_price(product, 1.0)
            except Exception:
                price = product.currency_id._convert(
                    product.lst_price, currency, company, fields.Date.today())
        else:
            currency = product.currency_id or company.currency_id
            price = product.lst_price
        # Receipt partner's company if known, else the current company's partner
        source = partner or company.partner_id
        size = product.label_size
        if not size:
            values = product.product_template_attribute_value_ids.filtered(
                lambda v: 'size' in (v.attribute_id.name or '').lower())
            size = ', '.join(values.mapped('name'))
        return {
            'category': product.categ_id.name or '',
            'barcode': product.barcode or '',
            'barcode_img': self._ars_barcode_img(product.barcode),
            'name': product.with_context(display_default_code=False).name or '',
            'size': size or '',
            'price': '%s %s' % (currency.name, '{:,.2f}'.format(price)),
            'mfg': ('MFG. BY %s' % source.name.upper()) if source.name else '',
            'care_no': source.phone or '',
            'email': source.email or '',
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        per_row = self._ars_per_row()
        active_model = data.get('active_model') or 'product.product'
        partner_map = data.get('ars_partner_by_product') or {}
        pricelist = self.env['product.pricelist'].browse(data.get('ars_pricelist_id') or 0)
        qty_map = data.get('quantity_by_product') or {pid: 1 for pid in (docids or [])}

        labels = []
        for rec_id, qty in qty_map.items():
            record = self.env[active_model].browse(int(rec_id))
            if active_model == 'product.template':
                record = record.product_variant_id
            if not record:
                continue
            partner = self.env['res.partner'].browse(partner_map.get(str(record.id), 0))
            vals = self._ars_label_vals(record, partner, pricelist)
            labels.extend([vals] * self._ars_qty(qty))

        rows = []
        for i in range(0, len(labels), per_row):
            row = labels[i:i + per_row]
            row += [False] * (per_row - len(row))
            rows.append(row)
        return {'doc_ids': docids, 'doc_model': 'product.product', 'rows': rows}


class ReportArsLabel2Up(models.AbstractModel):
    _name = 'report.ramsha_label_aretx.report_ars_label_2up'
    _inherit = 'report.ramsha_label_aretx.mixin'
    _description = 'ARS Label 2-up'

    def _ars_per_row(self):
        return 2


class ReportArsLabel1Up(models.AbstractModel):
    _name = 'report.ramsha_label_aretx.report_ars_label_1up'
    _inherit = 'report.ramsha_label_aretx.mixin'
    _description = 'ARS Label 1-up'

    def _ars_per_row(self):
        return 1