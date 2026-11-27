from odoo import http
from odoo.http import request
from .ess_access import ess_required


class PortalESS(http.Controller):

    @http.route('/my/ess', type='http', auth='user', website=True)
    @ess_required
    def portal_ess_dashboard(self, **kwargs):
        """Render the Employee Self Service dashboard (Time Off + Attendance options)."""
        return request.render('pharma_portal_timeoff_aretx.portal_ess_dashboard_template', {
            'page_name': 'ess',
        })
