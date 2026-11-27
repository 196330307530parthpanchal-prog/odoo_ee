import math

from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools.misc import format_duration

from .portal_time_off import PortalTimeOff
from .ess_access import ess_required


class PortalAllocationRequest(http.Controller):

    def _get_employee(self):
        """Return the employee linked to the logged-in user (empty if none)."""
        return request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)

    def _get_requestable_leave_types(self, employee):
        """Return leave types an employee may request an allocation for.

        Same rule as Odoo's backend (requires allocation + employee requests
        allowed). Types with 'no validation' are excluded because Odoo would
        approve them automatically on creation.
        """
        return request.env['hr.leave.type'].sudo().search([
            ('requires_allocation', '=', 'yes'),
            ('employee_requests', '=', 'yes'),
            ('allocation_validation_type', '!=', 'no_validation'),
        ])

    def _get_leave_type_options(self, employee, leave_types):
        """Build dropdown entries: Odoo's own label, the unit (day/hour) and extra hours available."""
        options = []
        has_overtime = 'overtime_deductible' in leave_types._fields
        for leave_type in leave_types:
            overtime = ''
            if has_overtime and leave_type.overtime_deductible and employee.total_overtime > 0:
                overtime = format_duration(employee.total_overtime)
            options.append({
                'id': leave_type.id,
                'label': leave_type.with_context(employee_id=employee.id, request_type='allocation').display_name,
                'request_unit': leave_type.request_unit,
                'overtime': overtime,
            })
        return options

    def _render_form(self, employee, error=None, values=None):
        """Render the allocation request form, optionally with an error and previous values."""
        leave_types = self._get_requestable_leave_types(employee) if employee else request.env['hr.leave.type']
        return request.render('pharma_portal_timeoff_aretx.portal_allocation_request_form', {
            'leave_type_options': self._get_leave_type_options(employee, leave_types) if employee else [],
            'error': error,
            'values': values or {},
            'csrf_token': request.csrf_token(),
            'page_name': 'allocation_request',
        })

    @http.route('/my/allocations/request', type='http', auth='user', website=True)
    @ess_required
    def portal_allocation_request(self, **kwargs):
        """Show the 'Request a Leave Allocation' form."""
        return self._render_form(self._get_employee())

    @http.route('/my/allocations/request/submit', type='http', auth='user', website=True, methods=['POST'])
    @ess_required
    def portal_allocation_request_submit(self, **post):
        """Validate the form and create an allocation request awaiting approval."""
        employee = self._get_employee()
        if not employee:
            return self._render_form(employee, error="Your account is not linked to an employee record.")

        values = {
            'holiday_status_id': post.get('holiday_status_id', ''),
            'duration': post.get('duration', ''),
            'reason': (post.get('reason') or '').strip(),
        }

        # Time off type must be one of the types offered in the dropdown.
        leave_types = self._get_requestable_leave_types(employee)
        leave_type = leave_types.filtered(lambda t: str(t.id) == values['holiday_status_id'])
        if not leave_type:
            return self._render_form(employee, error="Please select a valid time off type.", values=values)

        # Duration (days or hours, depending on the type) must be a positive, finite number.
        is_hours = leave_type.request_unit == 'hour'
        try:
            duration = float(values['duration'])
        except ValueError:
            duration = 0.0
        if not math.isfinite(duration) or duration <= 0:
            error = "Number of hours must be greater than 0." if is_hours else "Number of days must be greater than 0."
            return self._render_form(employee, error=error, values=values)

        # A reason is required so the approver knows why it is requested.
        if not values['reason']:
            return self._render_form(employee, error="Please enter a reason for your request.", values=values)

        # The employee always comes from the logged-in user and the state is left
        # untouched, so Odoo creates the request as 'To Approve' for the approver.
        # The reason goes in Odoo's 'Reasons' (notes) field; the title stays Odoo's default.
        # Start date defaults to today and the end date stays empty (no limit).
        vals = {
            'employee_id': employee.id,
            'holiday_status_id': leave_type.id,
            'notes': values['reason'],
        }
        if is_hours:
            # Hour based types: keep days and hours consistent using the employee's hours per day.
            hours_per_day = employee._get_hours_per_day(fields.Date.today())
            if hours_per_day <= 0:
                return self._render_form(
                    employee, error="Your working schedule has no working hours.", values=values)
            vals.update({'number_of_hours_display': duration, 'number_of_days': duration / hours_per_day})
        else:
            vals['number_of_days'] = duration
        try:
            request.env['hr.leave.allocation'].sudo().create(vals)
        except (UserError, ValidationError) as e:
            return self._render_form(employee, error=str(e), values=values)

        return request.redirect('/my/allocations')


class PortalAllocationHistory(PortalTimeOff):

    @http.route()
    def portal_my_allocations(self, **kwargs):
        """Extend My Leave Allocations with the user's allocation request history."""
        response = super().portal_my_allocations(**kwargs)
        # Only requests created by this user for their own employee record, newest first.
        response.qcontext['allocation_requests'] = request.env['hr.leave.allocation'].sudo().search([
            ('employee_id.user_id', '=', request.env.user.id),
            ('create_uid', '=', request.env.user.id),
        ], order='create_date desc')
        # The message shows while any request is waiting for approval, so it
        # disappears once approved/refused and returns if set back to To Approve.
        response.qcontext['allocation_pending'] = any(
            req.state in ('confirm', 'validate1') for req in response.qcontext['allocation_requests'])
        return response