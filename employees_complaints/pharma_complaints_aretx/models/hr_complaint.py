from odoo import fields, models


class HrComplaint(models.Model):
    _name = "hr.complaint"
    _description = "Employee Complaint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "employee_id"
    _order = "id desc"

    employee_id = fields.Many2one(
        "hr.employee", string="Employee Name", required=True, index=True)
    complaint_type_id = fields.Many2one(
        "hr.complaint.type", string="Complaint Type", required=True)
    description = fields.Text(string="Description", required=True)
    severity = fields.Selection(
        [("low", "Low"), ("moderate", "Moderate"), ("high", "High")],
        string="Severity", required=True, default="low",tracking=True,)