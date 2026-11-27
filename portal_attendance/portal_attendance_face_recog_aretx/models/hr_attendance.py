from odoo import fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    # Check-in details
    check_in_image = fields.Image(
        string='Check-In Selfie', max_width=1024, max_height=1024, attachment=True)
    latitude = fields.Float(string='Check-In Latitude', digits=(10, 7))
    longitude = fields.Float(string='Check-In Longitude', digits=(10, 7))

    # Check-out details
    check_out_image = fields.Image(
        string='Check-Out Selfie', max_width=1024, max_height=1024, attachment=True)
    out_latitude = fields.Float(string='Check-Out Latitude', digits=(10, 7))
    out_longitude = fields.Float(string='Check-Out Longitude', digits=(10, 7))
