from odoo import fields, models


class PharmaAttendanceDebugLog(models.Model):
    _name = 'pharma.attendance.debug.log'
    _description = 'Attendance Calculation Debug Log'
    _order = 'create_date desc, attendance_date desc, employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', index=True, readonly=True)
    attendance_date = fields.Date(string='Attendance Date', index=True, readonly=True)
    first_in = fields.Char(string='First In', readonly=True)
    last_out = fields.Char(string='Last Out', readonly=True)
    punch_data = fields.Text(string='Punches', readonly=True)
    worked_minutes = fields.Integer(string='Worked Minutes', readonly=True)
    worked_hours = fields.Float(string='Worked Hours', readonly=True, digits=(16, 2))
    has_pair = fields.Boolean(string='Has Pair', readonly=True)
    status = fields.Char(string='Status', readonly=True)
    status_kind = fields.Char(string='Status Kind', readonly=True)
    shift_name = fields.Char(string='Shift', readonly=True)
    shift_detail = fields.Text(string='Shift Detail', readonly=True)
    required_minutes = fields.Integer(string='Required Minutes', readonly=True)
    pair_limit = fields.Integer(string='Pair Limit (Minutes)', readonly=True)
    is_multi = fields.Boolean(string='Multiple Shift/Pairs', readonly=True)
    report_from = fields.Date(string='Report From', readonly=True)
    report_to = fields.Date(string='Report To', readonly=True)
    create_date = fields.Datetime(string='Logged At', readonly=True)
