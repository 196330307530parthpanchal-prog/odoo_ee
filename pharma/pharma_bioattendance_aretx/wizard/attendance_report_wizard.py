import base64
import io
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class PharmaAttendanceReportWizard(models.TransientModel):
    _name = "pharma.attendance.report.wizard"
    _description = "Pharma Attendance Excel Report Wizard"

    start_date = fields.Date(
        string="Start Date",
        required=True,
        default=fields.Date.context_today,
    )

    end_date = fields.Date(
        string="End Date",
        required=True,
        default=fields.Date.context_today,
    )

    report_file = fields.Binary(
        string="Report",
        readonly=True,
    )

    report_filename = fields.Char(
        string="Report Filename",
        readonly=True,
    )
    can_finalize = fields.Boolean(
        string="Can Finalize",
        compute="_compute_finalization_buttons",
    )

    can_redo_finalization = fields.Boolean(
        string="Can Redo Finalization",
        compute="_compute_finalization_buttons",
    )

    def action_download_report(self):
        self.ensure_one()

        if self.start_date > self.end_date:
            raise ValidationError(_("Start Date cannot be later than End Date."))

        output = io.BytesIO()

        report_model = self.env["report.pharma.attendance.xlsx"]

        workbook = report_model._create_workbook(
            output,
            self,
        )

        workbook.close()
        output.seek(0)

        filename = (
            "Attendance Sheet - "
            f'{self.start_date.strftime("%d-%m-%Y")} to '
            f'{self.end_date.strftime("%d-%m-%Y")}.xlsx'
        )

        self.write(
            {
                "report_file": base64.b64encode(output.read()),
                "report_filename": filename,
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": (
                "/web/content/"
                f"?model={self._name}"
                f"&id={self.id}"
                f"&field=report_file"
                f"&filename={quote(filename)}"
                f"&download=true"
            ),
            "target": "self",
        }

    def action_finalize_attendance(self):
        self.ensure_one()

        if not self.start_date or not self.end_date:
            raise ValidationError(_("Please select both Start Date and End Date."))

        if self.start_date > self.end_date:
            raise ValidationError(_("Start Date cannot be later than End Date."))

        AttendanceSheet = self.env["pharma.attendance.sheet"]

        # Check exact finalized period.
        exact_existing = AttendanceSheet.search(
            [
                ("date_from", "=", self.start_date),
                ("date_to", "=", self.end_date),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if exact_existing:
            raise UserError(
                _(
                    "This attendance period has already been finalized.\n\n"
                    "Period: %s to %s\n"
                    "Finalized By: %s\n"
                    "Finalized On: %s"
                )
                % (
                    exact_existing.date_from.strftime("%d/%m/%Y"),
                    exact_existing.date_to.strftime("%d/%m/%Y"),
                    exact_existing.finalized_by.name or "Unknown",
                    fields.Datetime.context_timestamp(
                        self,
                        exact_existing.finalized_on,
                    ).strftime("%d/%m/%Y %I:%M %p"),
                )
            )

        # Check overlapping finalized period.
        overlapping = AttendanceSheet.search(
            [
                ("state", "=", "finalized"),
                ("date_from", "<=", self.end_date),
                ("date_to", ">=", self.start_date),
            ],
            limit=1,
        )

        if overlapping:
            raise UserError(
                _(
                    "This attendance period overlaps with an attendance "
                    "period that has already been finalized.\n\n"
                    "Existing finalized period: %s to %s"
                )
                % (
                    overlapping.date_from.strftime("%d/%m/%Y"),
                    overlapping.date_to.strftime("%d/%m/%Y"),
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Confirm Attendance Finalization"),
            "res_model": "pharma.attendance.finalize.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_operation": "finalize",
                "default_date_from": self.start_date,
                "default_date_to": self.end_date,
                "attendance_wizard_id": self.id,
            },
        }

    def action_redo_finalization(self):
        self.ensure_one()

        if not self.start_date or not self.end_date:
            raise ValidationError(_("Please select both Start Date and End Date."))

        if self.start_date > self.end_date:
            raise ValidationError(_("Start Date cannot be later than End Date."))

        AttendanceSheet = self.env["pharma.attendance.sheet"]

        attendance_sheet = AttendanceSheet.search(
            [
                ("date_from", "=", self.start_date),
                ("date_to", "=", self.end_date),
                ("state", "=", "finalized"),
            ],
            limit=1,
        )

        if not attendance_sheet:
            raise UserError(
                _(
                    "There is no finalized attendance sheet for "
                    "the selected period.\n\n"
                    "Period: %s to %s"
                )
                % (
                    self.start_date.strftime("%d/%m/%Y"),
                    self.end_date.strftime("%d/%m/%Y"),
                )
            )

        return {
            "type": "ir.actions.act_window",
            "name": _("Confirm Redo Finalization"),
            "res_model": "pharma.attendance.finalize.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_operation": "redo",
                "default_date_from": self.start_date,
                "default_date_to": self.end_date,
                "default_attendance_sheet_id": attendance_sheet.id,
                "attendance_wizard_id": self.id,
            },
        }

    @api.depends("start_date", "end_date")
    def _compute_finalization_buttons(self):
        AttendanceSheet = self.env["pharma.attendance.sheet"]

        for wizard in self:
            wizard.can_finalize = True
            wizard.can_redo_finalization = False

            if not wizard.start_date or not wizard.end_date:
                continue

            if wizard.start_date > wizard.end_date:
                wizard.can_finalize = False
                continue

            finalized_sheet = AttendanceSheet.search(
                [
                    ("date_from", "=", wizard.start_date),
                    ("date_to", "=", wizard.end_date),
                    ("state", "=", "finalized"),
                ],
                limit=1,
            )

            if finalized_sheet:
                wizard.can_finalize = False
                wizard.can_redo_finalization = True
