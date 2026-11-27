from datetime import datetime

import pytz

from odoo import http
from odoo.http import request

from .ess_access import ess_required


class PortalPublicHolidays(http.Controller):

    @http.route('/my/public_holidays', type='http', auth='user', website=True)
    @ess_required
    def portal_public_holidays(self, year=None, **kwargs):
        """Read-only list of the public holidays of the employee's company / working schedule."""
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.env.user.id)], limit=1)
        calendar = employee.resource_calendar_id
        company = employee.company_id or request.env.company
        tz = pytz.timezone(calendar.tz or request.env.user.tz or 'UTC')
        today = datetime.now(tz).date()

        # Public holidays = global leaves (not tied to a resource) of the company,
        # for the employee's working schedule (or for every schedule).
        domain = [('resource_id', '=', False), ('company_id', '=', company.id)]
        if calendar:
            domain += ['|', ('calendar_id', '=', False), ('calendar_id', '=', calendar.id)]
        else:
            domain += [('calendar_id', '=', False)]
        leaves = request.env['resource.calendar.leaves'].sudo().search(domain, order='date_from')

        def local_date(value):
            return pytz.UTC.localize(value).astimezone(tz).date()

        years = {today.year}
        for leave in leaves:
            years.add(local_date(leave.date_from).year)
            years.add(local_date(leave.date_to).year)
        years = sorted(years, reverse=True)
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = today.year
        if year not in years:
            year = today.year

        holidays = []
        for leave in leaves:
            start, end = local_date(leave.date_from), local_date(leave.date_to)
            if start.year > year or end.year < year:
                continue
            holidays.append({
                'name': leave.name,
                'start': start,
                'end': end,
                'days': (end - start).days + 1,
                'is_past': end < today,
            })

        return request.render('pharma_portal_timeoff_aretx.portal_public_holidays_template', {
            'page_name': 'public_holidays',
            'holidays': holidays,
            'years': years,
            'year': year,
        })
