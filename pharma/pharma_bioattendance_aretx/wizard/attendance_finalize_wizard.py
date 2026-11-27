from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PharmaAttendanceFinalizeWizard(models.TransientModel):
    _name = "pharma.attendance.finalize.wizard"
    _description = "Confirm Attendance Finalization"

    operation = fields.Selection(
        [
            ("finalize", "Finalize"),
            ("redo", "Redo Finalization"),
        ],
        required=True,
        readonly=True,
    )

    date_from = fields.Date(
        string="From Date",
        required=True,
        readonly=True,
    )

    date_to = fields.Date(
        string="To Date",
        required=True,
        readonly=True,
    )

    attendance_sheet_id = fields.Many2one(
        "pharma.attendance.sheet",
        string="Attendance Sheet",
        readonly=True,
    )

    def action_back(self):
        self.ensure_one()

        wizard_id = self.env.context.get("attendance_wizard_id")

        if wizard_id:
            return {
                "type": "ir.actions.act_window",
                "name": _("Generate Attendance Excel"),
                "res_model": "pharma.attendance.report.wizard",
                "view_mode": "form",
                "res_id": wizard_id,
                "target": "new",
            }

        return {
            "type": "ir.actions.act_window_close",
        }

    def action_confirm(self):
        self.ensure_one()

        if self.date_from > self.date_to:
            raise ValidationError(_("Start Date cannot be later than End Date."))

        AttendanceSheet = self.env["pharma.attendance.sheet"]

        # ---------------------------------------------------------
        # FINALIZE
        # ---------------------------------------------------------
        if self.operation == "finalize":

            # First check whether the exact period is already finalized.
            exact_existing = AttendanceSheet.search(
                [
                    ("date_from", "=", self.date_from),
                    ("date_to", "=", self.date_to),
                    ("state", "=", "finalized"),
                ],
                limit=1,
            )

            if exact_existing:
                raise UserError(
                    _(
                        "Attendance for this period has already "
                        "been finalized.\n\n"
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

            # Then check for any overlapping finalized period.
            overlapping = AttendanceSheet.search(
                [
                    ("state", "=", "finalized"),
                    ("date_from", "<=", self.date_to),
                    ("date_to", ">=", self.date_from),
                ],
                limit=1,
            )

            if overlapping:
                raise UserError(
                    _(
                        "This attendance period cannot be finalized "
                        "because it overlaps with an attendance period "
                        "that has already been finalized.\n\n"
                        "Existing finalized period: %s to %s"
                    )
                    % (
                        overlapping.date_from.strftime("%d/%m/%Y"),
                        overlapping.date_to.strftime("%d/%m/%Y"),
                    )
                )

            AttendanceSheet.create(
                {
                    "date_from": self.date_from,
                    "date_to": self.date_to,
                    "state": "finalized",
                    "finalized_on": fields.Datetime.now(),
                    "finalized_by": self.env.user.id,
                }
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Attendance Finalized"),
                    "message": _(
                        "Attendance from %s to %s has been finalized. "
                        "Leave registration for this period is now locked."
                    )
                    % (
                        self.date_from.strftime("%d/%m/%Y"),
                        self.date_to.strftime("%d/%m/%Y"),
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }

        # ---------------------------------------------------------
        # REDO FINALIZATION
        # ---------------------------------------------------------
        if self.operation == "redo":

            attendance_sheet = self.attendance_sheet_id

            if not attendance_sheet:
                attendance_sheet = AttendanceSheet.search(
                    [
                        ("date_from", "=", self.date_from),
                        ("date_to", "=", self.date_to),
                        ("state", "=", "finalized"),
                    ],
                    limit=1,
                )

            if not attendance_sheet:
                raise UserError(
                    _("No finalized attendance sheet was found " "for %s to %s.")
                    % (
                        self.date_from.strftime("%d/%m/%Y"),
                        self.date_to.strftime("%d/%m/%Y"),
                    )
                )

            attendance_sheet.write(
                {
                    "state": "unfinalized",
                    "unfinalized_on": fields.Datetime.now(),
                    "unfinalized_by": self.env.user.id,
                }
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Attendance Finalization Reopened"),
                    "message": _(
                        "Attendance from %s to %s has been reopened. "
                        "Leave registration for this period is now allowed "
                        "again, subject to the leave registration rules."
                    )
                    % (
                        self.date_from.strftime("%d/%m/%Y"),
                        self.date_to.strftime("%d/%m/%Y"),
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }

        raise UserError(_("Invalid attendance finalization operation."))
