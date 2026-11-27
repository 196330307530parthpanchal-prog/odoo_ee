from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request
from odoo.addons.website.controllers.main import Website

from .ess_access import has_ess_access


class PortalHomeESS(CustomerPortal):

    @http.route()
    def home(self, **kw):
        """Portal Employees only get Employee Self Service: /my (and /my/home) opens ESS directly."""
        if has_ess_access():
            return request.redirect('/my/ess')
        return super().home(**kw)


class WebsiteHomeESS(Website):

    @http.route()
    def index(self, **kw):
        """Portal Employees opening the site root (/) go straight to Employee Self Service."""
        if has_ess_access():
            return request.redirect('/my/ess')
        return super().index(**kw)
