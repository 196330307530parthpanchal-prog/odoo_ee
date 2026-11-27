from odoo import fields, models


class HrComplaintType(models.Model):
    _name = "hr.complaint.type"
    _description = "Complaint Type"
    _order = "name"

    name = fields.Char(string="Complaint Type", required=True)
    description = fields.Text(string="Description")