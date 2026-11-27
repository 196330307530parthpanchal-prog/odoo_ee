from odoo import models


class ResUsers(models.Model):
    _inherit = 'res.users'

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('pa_skip_ess_sync'):
            self._pa_sync_portal_employee_group()
        return res

    def _pa_sync_portal_employee_group(self):
        """Portal users linked to an employee always get Employee Self Service."""
        group = self.env.ref('pharma_portal_timeoff_aretx.group_portal_employee',
                             raise_if_not_found=False)
        if not group:
            return
        groups_field = 'group_ids' if 'group_ids' in self._fields else 'groups_id'
        for user in self.sudo().filtered(lambda u: u.share and u.employee_ids):
            if user.has_group('base.group_portal') and group not in user[groups_field]:
                user.with_context(pa_skip_ess_sync=True).write(
                    {groups_field: [(4, group.id)]})