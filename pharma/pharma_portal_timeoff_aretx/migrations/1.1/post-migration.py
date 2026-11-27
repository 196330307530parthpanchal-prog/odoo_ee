from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Existing portal users linked to an employee keep ESS access after the upgrade."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref('pharma_portal_timeoff_aretx.group_portal_employee')
    groups_field = 'group_ids' if 'group_ids' in env['res.users']._fields else 'groups_id'
    employees = env['hr.employee'].with_context(active_test=False).search([('user_id', '!=', False)])
    users = employees.user_id.filtered(lambda u: u.has_group('base.group_portal'))
    users.write({groups_field: [(4, group.id)]})
