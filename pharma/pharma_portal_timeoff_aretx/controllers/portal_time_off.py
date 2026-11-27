import base64

from odoo import http
from odoo.http import request
from .ess_access import ess_required


def time_to_float(value):
    """Convert an 'HH:MM' string from the portal form to a float number of hours."""
    try:
        hours, minutes = value.split(':')[:2]
        return int(hours) + int(minutes) / 60.0
    except (AttributeError, ValueError):
        return 0.0


def get_leave_unit_vals(leave_type, params):
    """Return the extra hr.leave values for Half Day / Custom Hours chosen on the portal form.

    Half Day is only allowed for half-day/hour leave types and Custom Hours only
    for hour leave types, as in the Odoo backend.
    """
    half_day = params.get('half_day') and leave_type.request_unit in ('half_day', 'hour')
    custom_hours = params.get('custom_hours') and leave_type.request_unit == 'hour' and not half_day
    if half_day:
        period = params.get('half_day_period')
        return {
            'request_unit_half': True,
            'request_date_from_period': period if period in ('am', 'pm') else 'am',
            'request_date_to': params.get('date_from'),
        }
    if custom_hours:
        return {
            'request_unit_hours': True,
            'request_hour_from': time_to_float(params.get('hour_from')),
            'request_hour_to': time_to_float(params.get('hour_to')),
            'request_date_to': params.get('date_from'),
        }
    return {}


class PortalTimeOff(http.Controller):

    @http.route(['/my/time_off'], type='http', auth="user", website=True)
    @ess_required
    def portal_time_off(self, **kwargs):
        user = request.env.user
        time_offs = request.env['hr.leave'].sudo().search([('employee_id.user_id', '=', user.id)])
        print("time off is:::", time_offs)
        leave_types = request.env['hr.leave.type'].sudo().search([])
        print("leave_types is:::", leave_types)
        return request.render('pharma_portal_timeoff_aretx.portal_time_off_page', {
            'time_offs': time_offs,
            'leave_types': leave_types,
            'allocations': self._get_balance_cards(),
            'page_name': 'time_off',
        })

    def _get_balance_cards(self):
        """Return allocated days and remaining balance per leave type for the logged-in employee."""
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        cards = []
        if employee:
            # Only leave types the employee can actually use
            leave_types = request.env['hr.leave.type'].sudo().search([
                '|',
                ('requires_allocation', '=', 'no'),
                '&',
                ('has_valid_allocation', '=', True),
                '|',
                ('allows_negative', '=', True),
                '&',
                ('virtual_remaining_leaves', '>', 0),
                ('allows_negative', '=', False),
            ])
            for leave_type in leave_types:
                cards.append({
                    'id': leave_type.id,
                    'leave_name': leave_type.name,
                    'remain_leave': leave_type.virtual_remaining_leaves,
                    'total_leave': leave_type.max_leaves,
                })
        return cards

    @http.route(['/my/apply_time_off'], type='http', auth="user", website=True)
    @ess_required
    def portal_apply_time_off(self, **kwargs):
        """
        Render the 'Apply Time Off' page where the user can submit their leave application.
        """
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        time_off_types = []

        if employee:
            # Apply the domain conditions to filter time off types
            leave_types = request.env['hr.leave.type'].sudo().search([
                '|',
                ('requires_allocation', '=', 'no'),
                '&',
                ('has_valid_allocation', '=', True),
                '|',
                ('allows_negative', '=', True),
                '&',
                ('virtual_remaining_leaves', '>', 0),
                ('allows_negative', '=', False),
            ])

            for leave_type in leave_types:
                # Use Odoo's own label for this employee (days or hours available)
                time_off_types.append({
                    'id': leave_type.id,
                    'label': leave_type.with_context(employee_id=employee.id).display_name,
                    'request_unit': leave_type.request_unit,
                    'support_document': leave_type.support_document,
                })

        return request.render('pharma_portal_timeoff_aretx.portal_apply_time_off_form', {
            'time_off_types': time_off_types,
            'csrf_token': request.csrf_token(),
            'page_name': 'apply_time_off',
        })

    @http.route(['/my/apply_time_off/submit'], type='http', auth="user", website=True, methods=['POST'])
    @ess_required
    def portal_submit_time_off(self, **post):
        """
        Handle the form submission for time off application.
        """
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)

        if not employee:
            return request.redirect('/my/home')

        leave_type = request.env['hr.leave.type'].sudo().browse(int(post.get('time_off_type')))
        vals = {
            'holiday_status_id': leave_type.id,
            'employee_id': employee.id,
            'request_date_from': post.get('date_from'),
            'request_date_to': post.get('date_to'),
            'name': post.get('description'),
        }
        # Half Day / Custom Hours (hour based leave types)
        vals.update(get_leave_unit_vals(leave_type, post))
        leave = request.env['hr.leave'].sudo().create(vals)

        # Supporting documents are only accepted for types that allow them.
        if leave_type.support_document:
            for uploaded in request.httprequest.files.getlist('supporting_documents'):
                if uploaded.filename:
                    request.env['ir.attachment'].sudo().create({
                        'name': uploaded.filename,
                        'datas': base64.b64encode(uploaded.read()),
                        'res_model': 'hr.leave',
                        'res_id': leave.id,
                    })

        return request.redirect('/my/home')

    @http.route(['/my/allocations'], type='http', auth="user", website=True)
    @ess_required
    def portal_my_allocations(self, **kwargs):
        """
        Render the 'My Leave Allocations' page (allocation requests; balances are on My Time Offs).
        """
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        return request.render('pharma_portal_timeoff_aretx.portal_my_allocations', {
            'employee': employee,
            'page_name': 'leave_allocations',
        })