from odoo import api, fields, models


class PharmaBiometricMispunch(models.Model):
    _name = "pharma.biometric.mispunch"
    _description = "Biometric Attendance Mispunch"
    _order = "punch_datetime desc, id desc"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        ondelete="cascade",
        index=True,
    )

    shift_calendar_id = fields.Many2one(
        "resource.calendar",
        string="Shift",
        ondelete="restrict",
        index=True,
    )

    punch_datetime = fields.Datetime(
        string="Punch Date/Time",
        required=True,
        index=True,
    )

    punch_type = fields.Selection(
        [
            ("missing_out", "Missing Checkout"),
            ("unmatched", "Unmatched Punch"),
        ],
        string="Punch Type",
        required=True,
    )

    reason = fields.Text(
        string="Reason",
    )

    state = fields.Selection(
        [
            ("detected", "Detected"),
            ("resolved", "Resolved"),
        ],
        string="Status",
        default="detected",
        required=True,
        index=True,
    )

    attendance_id = fields.Many2one(
        "hr.attendance",
        string="Resolved Attendance",
        ondelete="set null",
    )

    # -------------------------------------------------------------
    # EMAIL NOTIFICATION
    # -------------------------------------------------------------

    email_sent = fields.Boolean(
        string="Email Sent",
        default=False,
        index=True,
    )

    @api.model
    def cron_send_mispunch_emails(self):
        """Send email notifications for detected mispunches."""

        mispunches = self.search([
            ("state", "=", "detected"),
            ("email_sent", "=", False),
        ])

        template = self.env.ref(
            "pharma_bioattendance_aretx.email_template_mispunch_notification",
            raise_if_not_found=False,
        )

        if not template:
            return

        for mispunch in mispunches:
            employee = mispunch.employee_id

            if not employee or not employee.work_email:
                continue

            template.send_mail(
                mispunch.id,
                force_send=True,
            )

            mispunch.email_sent = True