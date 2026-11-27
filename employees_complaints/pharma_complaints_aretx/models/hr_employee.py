from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    complaint_count = fields.Integer(
        string="Complaints", compute="_compute_complaint_count",
        groups="hr.group_hr_user")

    def _compute_complaint_count(self):
        data = self.env["hr.complaint"]._read_group(
            [("employee_id", "in", self.ids)],
            ["employee_id"], ["__count"])
        counts = {employee.id: count for employee, count in data}
        for employee in self:
            employee.complaint_count = counts.get(employee.id, 0)

    def action_open_complaints(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Complaints",
            "res_model": "hr.complaint",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "context": {"default_employee_id": self.id},
        }