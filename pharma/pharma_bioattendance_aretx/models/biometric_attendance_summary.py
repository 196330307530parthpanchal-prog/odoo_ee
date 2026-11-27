from odoo import models, fields


class BiometricAttendanceSummary(models.Model):
    _name = "biometric.attendance.summary"
    _description = "Biometric Attendance Daily Summary"
    _order = "attendance_date desc, employee_id"

    employee_id = fields.Many2one("hr.employee", string="Employee", index=True)
    employee_name = fields.Char(string="Employee Name (Device)")
    biometric_user_id = fields.Char(string="Biometric User ID")
    attendance_date = fields.Date(string="Date")
    device_id = fields.Many2one("biometric.device", string="Device")

    check_in = fields.Datetime(string="First Punch (Check In)")
    check_out = fields.Datetime(string="Last Punch (Check Out)")
    total_punches = fields.Integer(string="Total Punches")
    working_hours = fields.Float(string="Working Hours", digits=(16, 2))
    late = fields.Boolean(string="Late")
    punch_history = fields.Text(string="Punch History")

    office_start_time = fields.Char(string="Office Start Time", default="09:00")

    _sql_constraints = [
        (
            "unique_employee_date_device",
            "UNIQUE(biometric_user_id, attendance_date, device_id)",
            "Summary already exists for this employee, date and device.",
        )
    ]
