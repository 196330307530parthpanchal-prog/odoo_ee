from odoo import models, fields, api , _
from odoo.exceptions import UserError



class EmployeePortalUser(models.Model):
    _inherit = 'hr.employee'

    def action_create_portal_user(self):
        self.ensure_one()
        if not self.work_email and not self.private_email:
            raise UserError(
                _("Please set either a work email or a private email address before creating a portal user."))
        for record in self:
            if not record.user_id:
                user_vals = {
                    'name': record.name,
                    'login': record.work_email,
                    'email': record.work_email,
                    
                }
                # Portal Employee group: gives access to Employee Self Service (field is
                # called group_ids in Odoo 19, groups_id before)
                groups_field = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
                user_vals[groups_field] = [(6, 0, [
                    self.env.ref('base.group_portal').id,
                    self.env.ref('pharma_portal_timeoff_aretx.group_portal_employee').id,
                ])]
                user = self.env['res.users'].create(user_vals)
                record.user_id = user

    def action_create_user(self):
        """Create User button: creates a portal user (ESS enabled) for the employee."""
        self.ensure_one()
        if self.user_id:
            raise UserError(_("This employee is already linked to a user."))
        email = self.work_email or self.private_email
        if not email:
            raise UserError(
                _("Please set either a work email or a private email address before creating a user."))
        groups_field = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
        user = self.env['res.users'].create({
            'name': self.name,
            'login': email,
            'email': email,
            groups_field: [(6, 0, [
                self.env.ref('base.group_portal').id,
                self.env.ref('pharma_portal_timeoff_aretx.group_portal_employee').id,
            ])],
        })
        self.user_id = user