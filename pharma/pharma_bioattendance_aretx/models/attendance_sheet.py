from odoo import api, fields, models
from odoo.exceptions import ValidationError


class PharmaAttendanceSheet(models.Model):
    _name = "pharma.attendance.sheet"
    _description = "Finalized Attendance Sheet"
    _order = "date_from desc"

    date_from = fields.Date(
        string="From Date",
        required=True,
    )

    date_to = fields.Date(
        string="To Date",
        required=True,
    )

    state = fields.Selection(
        [
            ("finalized", "Finalized"),
            ("unfinalized", "Unfinalized"),
        ],
        string="Status",
        default="finalized",
        readonly=True,
    )

    finalized_on = fields.Datetime(
        string="Finalized On",
        default=fields.Datetime.now,
        readonly=True,
    )

    finalized_by = fields.Many2one(
        "res.users",
        string="Finalized By",
        default=lambda self: self.env.user,
        readonly=True,
    )

    unfinalized_on = fields.Datetime(
        string="Redo Finalization On",
        readonly=True,
    )

    unfinalized_by = fields.Many2one(
        "res.users",
        string="Redo Finalization By",
        readonly=True,
    )

    @api.constrains("date_from", "date_to")
    def _check_dates(self):
        for record in self:
            if record.date_to < record.date_from:
                raise ValidationError(
                    "The attendance sheet end date cannot be "
                    "earlier than the start date."
                )

    @api.constrains("date_from", "date_to")
    def _check_overlapping_periods(self):
        for record in self:
            overlapping = self.search(
                [
                    ("id", "!=", record.id),
                    ("state", "=", "finalized"),
                    ("date_from", "<=", record.date_to),
                    ("date_to", ">=", record.date_from),
                ],
                limit=1,
            )

            if overlapping:
                raise ValidationError(
                    "This attendance period overlaps with an "
                    "attendance period that has already been finalized.\n\n"
                    "Finalized period: %s to %s"
                    % (
                        overlapping.date_from.strftime("%d/%m/%Y"),
                        overlapping.date_to.strftime("%d/%m/%Y"),
                    )
                )
