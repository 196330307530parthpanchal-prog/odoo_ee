from odoo import SUPERUSER_ID, api
from odoo.addons.delivery_sign.models.res_company import DEFAULT_DELIVERY_SIGN_HTML


def migrate(cr, version):
    """Replace only the untouched first default layout (full grid) with the new one."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    for company in env['res.company'].with_context(active_test=False).search([]):
        if 'table table-bordered o_delivery_sign_table' in (company.delivery_sign_html or ''):
            company.delivery_sign_html = DEFAULT_DELIVERY_SIGN_HTML