from datetime import date

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ImportAttendanceWizard(models.TransientModel):
    _name = "import.attendance.wizard"
    _description = "Import Attendance Wizard"

    device_id = fields.Many2one(
        "biometric.device",
        string="Device",
        required=True,
    )
    attendance_date = fields.Date(
        string="Attendance Date",
        required=True,
        default=fields.Date.today,
    )

    def action_import(self):
        self.ensure_one()
        return self.device_id._import_attendance_for_date(self.attendance_date)
