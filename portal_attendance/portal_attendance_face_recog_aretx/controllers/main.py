import base64
import binascii
import logging
import math

from odoo import _, fields, http
from odoo.exceptions import UserError
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 5 * 1024 * 1024


class PortalAttendance(http.Controller):

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_employee():
        return request.env['hr.employee'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1)

    @staticmethod
    def _get_open_attendance(employee):
        return request.env['hr.attendance'].sudo().search(
            [('employee_id', '=', employee.id), ('check_out', '=', False)],
            order='check_in desc', limit=1)

    @staticmethod
    def _clean_image(image):
        """Return the bare base64 string of the selfie or raise ValueError."""
        if not image or not isinstance(image, str):
            raise ValueError(_('Please take a selfie first.'))
        if image.startswith('data:'):
            image = image.partition(',')[2]
        try:
            raw = base64.b64decode(image, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(_('The selfie could not be read. Please try again.'))
        if not raw:
            raise ValueError(_('Please take a selfie first.'))
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError(_('The selfie is too large.'))
        return image

    @staticmethod
    def _parse_coordinates(latitude, longitude):
        """Sanity-parse the coordinates (no location validation)."""
        try:
            lat, lon = float(latitude), float(longitude)
        except (TypeError, ValueError):
            raise ValueError(_('Your location is required. Please allow location access.'))
        if (not math.isfinite(lat) or not math.isfinite(lon)
                or abs(lat) > 90 or abs(lon) > 180):
            raise ValueError(_('Your location is invalid. Please try again.'))
        return lat, lon

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------
    @http.route('/portal_attendance/status', type='json', auth='user')
    def attendance_status(self):
        employee = self._get_employee()
        if not employee:
            return {'has_employee': False}
        return {
            'has_employee': True,
            'employee_name': employee.name,
            'checked_in': bool(self._get_open_attendance(employee)),
        }

    @http.route('/portal_attendance/submit', type='json', auth='user')
    def attendance_submit(self, image=None, latitude=None, longitude=None, **kwargs):
        employee = self._get_employee()
        if not employee:
            return {'success': False, 'message': _('No employee is linked to your user.')}

        try:
            selfie = self._clean_image(image)
            lat, lon = self._parse_coordinates(latitude, longitude)
        except ValueError as e:
            return {'success': False, 'message': str(e)}

        try:
            # Savepoint: if a constraint fails, nothing is left half-written.
            with request.env.cr.savepoint():
                now = fields.Datetime.now()
                open_attendance = self._get_open_attendance(employee)
                if open_attendance:
                    open_attendance.write({
                        'check_out': now,
                        'check_out_image': selfie,
                        'out_latitude': lat,
                        'out_longitude': lon,
                    })
                    action = 'check_out'
                    message = _('Thank you %s. Check-out successful.', employee.name)
                else:
                    request.env['hr.attendance'].sudo().create({
                        'employee_id': employee.id,
                        'check_in': now,
                        'check_in_image': selfie,
                        'latitude': lat,
                        'longitude': lon,
                    })
                    action = 'check_in'
                    message = _('Welcome %s. Check-in successful.', employee.name)
        except UserError as e:
            return {'success': False, 'message': str(e)}
        except Exception:
            _logger.exception('Portal attendance failed for employee %s', employee.id)
            return {'success': False, 'message': _('Could not record attendance. Please try again.')}

        return {'success': True, 'action': action, 'message': message}