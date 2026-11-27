from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from .portal_time_off import get_leave_unit_vals
from .ess_access import ess_required


class PortalTimeOffDays(http.Controller):

    @http.route('/my/apply_time_off/days', type='http', auth='user', website=True, methods=['GET'])
    @ess_required
    def portal_time_off_days(self, time_off_type=None, date_from=None, date_to=None, **kwargs):
        """Return Odoo's 'Requested (Days/Hours)' text for the chosen type, dates and hours."""
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        display = ''
        try:
            leave_type = request.env['hr.leave.type'].sudo().browse(int(time_off_type or 0)).exists()
            if employee and leave_type and date_from:
                vals = {
                    'employee_id': employee.id,
                    'holiday_status_id': leave_type.id,
                    'request_date_from': date_from,
                    'request_date_to': date_to,
                }
                # Half Day / Custom Hours use a single date
                vals.update(get_leave_unit_vals(leave_type, dict(kwargs, date_from=date_from)))
                # Day-based requests need an end date; half day / custom hours reuse the start date.
                if vals['request_date_to']:
                    vals['request_date_from'] = fields.Date.to_date(vals['request_date_from'])
                    vals['request_date_to'] = fields.Date.to_date(vals['request_date_to'])
                    # Unsaved leave: Odoo computes its duration (working days, holidays, hours)
                    # exactly as it will when the request is submitted.
                    display = request.env['hr.leave'].sudo().new(vals).duration_display
        except (ValueError, TypeError, UserError, ValidationError):
            display = ''
        return request.make_json_response({'display': display})