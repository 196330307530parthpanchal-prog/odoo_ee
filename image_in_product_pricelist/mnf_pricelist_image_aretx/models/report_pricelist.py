from odoo import models


class ReportProductPricelist(models.AbstractModel):
    _inherit = 'report.product.report_pricelist'

    def _get_product_data(self, is_product_tmpl, product, pricelist, quantities):        
        data = super()._get_product_data(is_product_tmpl, product, pricelist, quantities)
        img = product.image_256
        if img:
            if isinstance(img, bytes):
                img = img.decode()
            data['image_url'] = 'data:image/png;base64,%s' % img
        else:
            data['image_url'] = ''
        return data