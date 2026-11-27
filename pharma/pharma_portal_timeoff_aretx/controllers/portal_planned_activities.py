from werkzeug.exceptions import Forbidden, NotFound

from odoo import http
from odoo.http import request
from odoo.tools import html2plaintext

from .ess_access import ess_required


class PortalPlannedActivities(http.Controller):

    @http.route('/my/planned_activities', type='http', auth='user', website=True)
    @ess_required
    def portal_planned_activities(self, **kwargs):
        """Read-only list of the planned activities on the logged-in employee's own record."""
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        # Same activities the chatter shows under 'Planned Activities' - only for the
        # employee linked to the logged-in user, so nobody else's record is ever read.
        activities = request.env['mail.activity'].sudo().search([
            ('res_model', '=', 'hr.employee'),
            ('res_id', '=', employee.id),
            ('user_id', '=', request.env.user.id),
        ], order='date_deadline asc, id asc') if employee else request.env['mail.activity']
        # History: Odoo 18 deletes an activity once it is done and only keeps the chatter
        # note ('To-Do done : <name>'), so the history is read from those notes on the
        # employee's own record - those completed by this user, or originally assigned to them.
        history = []
        if employee:
            user = request.env.user
            messages = request.env['mail.message'].sudo().search([
                ('model', '=', 'hr.employee'),
                ('res_id', '=', employee.id),
                ('subtype_id', '=', request.env.ref('mail.mt_activities').id),
                ('mail_activity_type_id', '!=', False),
            ], order='date desc, id desc')
            for msg in messages:
                text = html2plaintext(msg.body or '').strip()
                first_line = text.split('\n')[0]
                if msg.author_id != user.partner_id and ('originally assigned to %s' % user.name) not in first_line:
                    continue
                name = first_line.split(' : ', 1)[1].strip() if ' : ' in first_line else (first_line or msg.mail_activity_type_id.name)
                history.append({'name': name, 'date': msg.date})
        return request.render('pharma_portal_timeoff_aretx.portal_planned_activities_template', {
            'page_name': 'planned_activities',
            'activities': activities,
            'history': history,
        })  

    @http.route('/my/planned_activities/<int:activity_id>/done', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    @ess_required
    def portal_planned_activity_done(self, activity_id, **kwargs):
        """Mark one of the logged-in employee's own planned activities as done."""
        user = request.env.user
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        activity = request.env['mail.activity'].sudo().browse(activity_id).exists()
        if not activity:
            raise NotFound()
        # Server-side ownership check: assigned to this user AND linked to this user's own employee record.
        if not employee or activity.res_model != 'hr.employee' \
                or activity.res_id != employee.id or activity.user_id != user:
            raise Forbidden()
        # Standard completion: posts the 'done' note in the employee chatter and removes the activity.
        activity.action_feedback()
        return request.redirect('/my/planned_activities')