from odoo import fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import email_normalize

from ..models.portal_private_request import PRIVATE_DETAIL_GROUPS, PRIVATE_FIELDS
from .ess_access import ess_required

TEXT_FIELDS = [
    'private_street', 'private_street2', 'private_city', 'private_zip', 'private_phone',
    'emergency_contact', 'emergency_phone', 'spouse_complete_name',
]


class PortalPrivateDetails(http.Controller):

    def _get_employee(self):
        """Employee linked to the logged-in user (empty if none) - nobody else's record is ever read."""
        return request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)

    def _get_marital_options(self):
        return request.env['hr.employee']._fields['marital']._description_selection(request.env)

    def _get_states(self, country_id):
        if not str(country_id or '').isdigit():
            return []
        states = request.env['res.country.state'].sudo().search([('country_id', '=', int(country_id))])
        return [(state.id, state.name) for state in states]

    # ------------------------------------------------------------------
    # View page: current details + approval status
    # ------------------------------------------------------------------
    @http.route('/my/private_details', type='http', auth='user', website=True)
    @ess_required
    def portal_private_details(self, submitted=None, **kwargs):
        employee = self._get_employee()
        Request = request.env['hr.employee.private.request'].sudo()
        requests_ = Request.search([('employee_id', '=', employee.id)]) if employee else Request
        employee_fields = request.env['hr.employee']._fields
        sections = [
            (title, [(employee_fields[n].string, Request._display_value(n, employee[n])) for n in names])
            for title, names in PRIVATE_DETAIL_GROUPS
        ] if employee else []
        return request.render('pharma_portal_timeoff_aretx.portal_private_details_template', {
            'page_name': 'private_details',
            'employee': employee,
            'sections': sections,
            'requests': requests_,
            'pending': requests_.filtered(lambda r: r.state == 'pending')[:1],
            'last_decided': requests_.filtered(lambda r: r.state != 'pending')[:1],
            'submitted': bool(submitted),
        })

    # ------------------------------------------------------------------
    # Edit form -> creates a pending request (employee record is NOT touched)
    # ------------------------------------------------------------------
    def _render_form(self, employee, values=None, error=None):
        if not values:
            values = {}
            for name in PRIVATE_FIELDS:
                value = employee[name]
                if name in ('private_state_id', 'private_country_id'):
                    values[name] = str(value.id) if value else ''
                elif name == 'spouse_birthdate':
                    values[name] = fields.Date.to_string(value) if value else ''
                elif name == 'children':
                    values[name] = str(value or 0)
                else:
                    values[name] = value or ''
        return request.render('pharma_portal_timeoff_aretx.portal_private_details_form', {
            'page_name': 'private_details_edit',
            'employee': employee,
            'values': values,
            'error': error,
            'countries': request.env['res.country'].sudo().search([]),
            'states': self._get_states(values.get('private_country_id')),
            'marital_options': self._get_marital_options(),
        })

    @http.route('/my/private_details/edit', type='http', auth='user', website=True)
    @ess_required
    def portal_private_details_edit(self, **kwargs):
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my/private_details')
        pending = request.env['hr.employee.private.request'].sudo().search_count(
            [('employee_id', '=', employee.id), ('state', '=', 'pending')])
        if pending:
            return request.redirect('/my/private_details')
        return self._render_form(employee)

    @http.route('/my/private_details/states', type='http', auth='user', website=True, methods=['GET'])
    @ess_required
    def portal_private_details_states(self, country_id=None, **kwargs):
        """States of a country, to refill the State dropdown when the country changes."""
        states = self._get_states(country_id)
        return request.make_json_response({'states': [{'id': sid, 'name': name} for sid, name in states]})

    @http.route('/my/private_details/submit', type='http', auth='user', website=True, methods=['POST'])
    @ess_required
    def portal_private_details_submit(self, **post):
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my/private_details')

        values = {name: (post.get(name) or '').strip() for name in PRIVATE_FIELDS}

        def fail(message):
            return self._render_form(employee, values=values, error=message)

        # Validate every value before anything is stored.
        vals = {name: values[name] for name in TEXT_FIELDS}
        if values['private_email']:
            email = email_normalize(values['private_email'])
            if not email:
                return fail("Please enter a valid private email address.")
            vals['private_email'] = email
        else:
            vals['private_email'] = ''

        country = request.env['res.country'].sudo().browse(
            int(values['private_country_id']) if values['private_country_id'].isdigit() else 0).exists()
        state = request.env['res.country.state'].sudo().browse(
            int(values['private_state_id']) if values['private_state_id'].isdigit() else 0).exists()
        if state and state.country_id != country:
            return fail("The selected state does not belong to the selected country.")
        vals['private_country_id'] = country.id
        vals['private_state_id'] = state.id

        if values['marital'] not in dict(self._get_marital_options()):
            return fail("Please select a valid marital status.")
        vals['marital'] = values['marital']

        try:
            vals['children'] = int(values['children'] or 0)
        except ValueError:
            vals['children'] = -1
        if vals['children'] < 0:
            return fail("Number of children must be zero or a positive whole number.")

        try:
            vals['spouse_birthdate'] = fields.Date.to_date(values['spouse_birthdate']) or False
        except (ValueError, TypeError):
            return fail("Please enter a valid spouse birthdate.")

        try:
            request.env['hr.employee.private.request'].sudo().submit_for_employee(employee, vals)
        except (UserError, ValidationError) as e:
            return fail(str(e))
        return request.redirect('/my/private_details?submitted=1')