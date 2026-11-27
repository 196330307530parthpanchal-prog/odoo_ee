from datetime import datetime

import pytz

from odoo import http
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.http import request
from .ess_access import ess_required

ITEMS_PER_PAGE = 20
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']


class PortalAttendance(http.Controller):

    def _get_user_tz(self):
        """Return the timezone object used to read each record's local year/month."""
        tz_name = request.env.context.get('tz') or request.env.user.tz or 'UTC'
        return pytz.timezone(tz_name)

    def _get_month_range_utc(self, year, month, tz):
        """Return naive UTC (start, end) datetimes covering one local month."""
        start = tz.localize(datetime(year, month, 1))
        end = tz.localize(datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1))
        to_utc = lambda dt: dt.astimezone(pytz.UTC).replace(tzinfo=None)
        return to_utc(start), to_utc(end)

    @http.route(['/my/attendance', '/my/attendance/page/<int:page>'], type='http', auth='user', website=True)
    @ess_required
    def portal_my_attendance(self, page=1, year=None, month=None, **kwargs):
        """Render the user's own attendance for one month (current month by default), paginated."""
        tz = self._get_user_tz()
        now = datetime.now(tz)
        # Restrict records to the employee linked to the current user, so
        # nobody can see another person's attendance.
        base_domain = [('employee_id.user_id', '=', request.env.user.id)]
        Attendance = request.env['hr.attendance'].sudo()

        # Year options: years the user has records in, plus the current year.
        years = {now.year}
        for check_in in Attendance.search(base_domain).mapped('check_in'):
            years.add(pytz.UTC.localize(check_in).astimezone(tz).year)
        searchbar_years = [(str(y), str(y)) for y in sorted(years, reverse=True)]
        searchbar_months = [(str(i + 1), name) for i, name in enumerate(MONTHS)]

        # Missing or invalid values fall back to the current year/month.
        if year not in dict(searchbar_years):
            year = str(now.year)
        if month not in dict(searchbar_months):
            month = str(now.month)

        # Only the selected month's records are loaded, one page at a time.
        start, end = self._get_month_range_utc(int(year), int(month), tz)
        domain = base_domain + [('check_in', '>=', start), ('check_in', '<', end)]
        pager = portal_pager(
            url='/my/attendance',
            url_args={'year': year, 'month': month},
            total=Attendance.search_count(domain),
            page=page,
            step=ITEMS_PER_PAGE,
        )
        attendances = Attendance.search(
            domain, order='check_in desc', limit=ITEMS_PER_PAGE, offset=pager['offset'])

        return request.render('pharma_portal_timeoff_aretx.portal_my_attendance_template', {
            'attendances': attendances,
            'page_name': 'my_attendance',
            'pager': pager,
            'searchbar_years': searchbar_years,
            'searchbar_months': searchbar_months,
            'year': year,
            'month': month,
            'year_label': dict(searchbar_years)[year],
            'month_label': dict(searchbar_months)[month],
        })
