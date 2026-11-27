import functools

from werkzeug.exceptions import Forbidden

from odoo.http import request

PORTAL_EMPLOYEE_GROUP = 'pharma_portal_timeoff_aretx.group_portal_employee'


def has_ess_access(user=None):
    """True when the user is a portal user that belongs to the 'Portal Employee' group."""
    user = user or request.env.user
    return bool(user and user.has_group('base.group_portal') and user.has_group(PORTAL_EMPLOYEE_GROUP))


def ess_required(func):
    """Route guard: only portal users in the 'Portal Employee' group may open the page.

    Place it *under* @http.route so the route keeps working as before.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not has_ess_access():
            raise Forbidden()
        return func(*args, **kwargs)
    return wrapper
