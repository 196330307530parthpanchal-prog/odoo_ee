import logging

import pytz

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)
from odoo.exceptions import UserError


class BiometricAttendanceLog(models.Model):
    _name = "biometric.attendance.log"
    _description = "Biometric Attendance Log"
    _order = "punch_time desc"

    employee_id = fields.Many2one("hr.employee", string="Employee", index=True)
    employee_name = fields.Char(string="Employee Name (Device)")
    biometric_user_id = fields.Char(string="Biometric User ID", required=True)
    attendance_date = fields.Date(string="Attendance Date", required=True)
    punch_time = fields.Datetime(string="Punch Time", required=True)
    device_id = fields.Many2one("biometric.device", string="Device")
    state = fields.Selection(
        [("imported", "Imported"), ("processed", "Processed")],
        string="State",
        default="imported",
    )

    _sql_constraints = [
        (
            "unique_user_punch",
            "UNIQUE(biometric_user_id, punch_time)",
            "Duplicate punch: same user and timestamp already exists.",
        )
    ]

    def action_process_attendance(self):
        # Always process every currently imported log.  The action is not
        # limited to the rows selected in the list view because the cron
        # also uses this method.
        logs = self.env["biometric.attendance.log"].search(
            [("state", "=", "imported")],
            order="punch_time asc, id asc",
        )

        if not logs:
            raise UserError(_("There are no Imported attendance logs to process."))

        _logger.info(
            "PROCESSING ALL IMPORTED BIOMETRIC LOGS | Count=%s | IDs=%s",
            len(logs),
            logs.ids,
        )

        punches = [
            {
                "enno": log.biometric_user_id,
                # punch_time is stored in UTC; mark it so it is never
                # converted a second time.
                "datetime": pytz.UTC.localize(log.punch_time),
            }
            for log in logs
        ]

        attendance_import = self.env["pharma.biometric.attendance"].create(
            {
                "name": _("Biometric Log Processing"),
                "state": "imported",
                "total_records": len(punches),
                "attendance_created": 0,
                "unmatched_employees": len(
                    set(
                        logs.filtered(lambda log: not log.employee_id).mapped(
                            "biometric_user_id"
                        )
                    )
                ),
                "unmatched_punches": len(
                    logs.filtered(lambda log: not log.employee_id)
                ),
            }
        )

        attendance_import._create_attendances(punches)

        logs.write({"state": "processed"})

        _logger.info(
            "BIOMETRIC LOG PROCESSING COMPLETED | Count=%s | State=Processed",
            len(logs),
        )

        return True