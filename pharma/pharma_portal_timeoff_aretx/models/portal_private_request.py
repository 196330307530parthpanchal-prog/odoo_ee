import json

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

# Employee "Private Information" fields a portal user may ask to change, by section.
PRIVATE_DETAIL_GROUPS = [
    ('Private Contact', [
        'private_street', 'private_street2', 'private_city', 'private_state_id',
        'private_zip', 'private_country_id', 'private_phone', 'private_email',
    ]),
    ('Emergency Contact', ['emergency_contact', 'emergency_phone']),
    ('Family Status', ['marital', 'spouse_complete_name', 'spouse_birthdate', 'children']),
]
PRIVATE_FIELDS = [name for _title, names in PRIVATE_DETAIL_GROUPS for name in names]


class EmployeePrivateRequest(models.Model):
    _name = 'hr.employee.private.request'
    _description = 'Employee Private Details Update Request'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    employee_id = fields.Many2one('hr.employee', required=True, ondelete='cascade', index=True, tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    state = fields.Selection([
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='pending', required=True, tracking=True, copy=False)
    requested_on = fields.Datetime(default=fields.Datetime.now, readonly=True, copy=False)
    decided_by = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    decided_on = fields.Datetime(readonly=True, copy=False)
    reject_reason = fields.Text(string='Rejection Reason', copy=False)

    # What the employee asked for (only the fields listed in changed_field_names are applied)
    changed_field_names = fields.Char(readonly=True, copy=False)
    old_values = fields.Text(readonly=True, copy=False, help="Values shown to the employee when the request was made.")
    change_summary = fields.Html(compute='_compute_change_summary', sanitize=False)

    private_street = fields.Char(string='Private Street')
    private_street2 = fields.Char(string='Private Street2')
    private_city = fields.Char(string='Private City')
    private_state_id = fields.Many2one('res.country.state', string='Private State', ondelete='set null')
    private_zip = fields.Char(string='Private Zip')
    private_country_id = fields.Many2one('res.country', string='Private Country', ondelete='set null')
    private_phone = fields.Char(string='Private Phone')
    private_email = fields.Char(string='Private Email')
    emergency_contact = fields.Char(string='Emergency Contact')
    emergency_phone = fields.Char(string='Emergency Phone')
    marital = fields.Selection(
        selection=lambda self: self.env['hr.employee']._fields['marital']._description_selection(self.env),
        string='Marital Status')
    spouse_complete_name = fields.Char(string="Spouse Complete Name")
    spouse_birthdate = fields.Date(string="Spouse Birthdate")
    children = fields.Integer(string='Number of Dependent Children')

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('employee_id.name')
    def _compute_name(self):
        for req in self:
            req.name = _("Private details update - %s", req.employee_id.name or '')

    @api.constrains('employee_id', 'state')
    def _check_single_pending(self):
        for req in self.filtered(lambda r: r.state == 'pending'):
            if self.search_count([('employee_id', '=', req.employee_id.id), ('state', '=', 'pending')]) > 1:
                raise ValidationError(_("This employee already has a pending private details request."))

    def get_change_lines(self):
        """Return [(label, old, new)] for the fields this request changes."""
        self.ensure_one()
        names = [n for n in (self.changed_field_names or '').split(',') if n in PRIVATE_FIELDS]
        employee_fields = self.env['hr.employee']._fields
        old = json.loads(self.old_values or '{}')
        return [(employee_fields[n].string, old.get(n, ''), self._display_value(n, self[n])) for n in names]

    @api.depends('changed_field_names', 'old_values', *PRIVATE_FIELDS)
    def _compute_change_summary(self):
        for req in self:
            rows = [
                Markup('<tr><td>%s</td><td>%s</td><td><b>%s</b></td></tr>') % (label, old or '-', new or '-')
                for label, old, new in req.get_change_lines()
            ]
            req.change_summary = Markup(
                '<table class="table table-sm"><thead><tr><th>Field</th><th>Current</th><th>Requested</th></tr>'
                '</thead><tbody>%s</tbody></table>') % Markup('').join(rows) if rows else False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _display_value(self, fname, value):
        """Human readable value of a private field (works for employee and request records)."""
        field = self._fields[fname]
        if field.type == 'many2one':
            return value.display_name if value else ''
        if field.type == 'selection':
            return dict(field._description_selection(self.env)).get(value, '') if value else ''
        if field.type == 'date':
            return fields.Date.to_string(value) if value else ''
        if field.type == 'integer':
            return str(value or 0)
        return value or ''

    @api.model
    def _normalize(self, fname, value):
        """Comparable form of a value, so 'no change' is detected reliably."""
        ftype = self._fields[fname].type
        if ftype == 'many2one':
            return value.id if isinstance(value, models.BaseModel) else (value or 0)
        if ftype == 'char':
            return (value or '').strip()
        if ftype == 'integer':
            return int(value or 0)
        if ftype == 'date':
            return fields.Date.to_date(value) or False
        return value or False

    @api.model
    def submit_for_employee(self, employee, vals):
        """Create a pending request holding only the values that differ from the employee record."""
        employee.ensure_one()
        if self.search_count([('employee_id', '=', employee.id), ('state', '=', 'pending')]):
            raise UserError(_("You already have a request waiting for HR approval."))
        changed, old = [], {}
        for fname in PRIVATE_FIELDS:
            if fname in vals and self._normalize(fname, employee[fname]) != self._normalize(fname, vals[fname]):
                changed.append(fname)
                old[fname] = self._display_value(fname, employee[fname])
        if not changed:
            raise UserError(_("You have not changed any detail."))
        create_vals = {fname: vals[fname] for fname in changed}
        create_vals.update({
            'employee_id': employee.id,
            'changed_field_names': ','.join(changed),
            'old_values': json.dumps(old),
        })
        return self.create(create_vals)

    # ------------------------------------------------------------------
    # HR actions
    # ------------------------------------------------------------------
    def _check_hr_rights(self):
        if not self.env.user.has_group('hr.group_hr_user'):
            raise AccessError(_("Only HR officers can approve or reject these requests."))

    def action_approve(self):
        """Copy the requested values to the employee record."""
        self._check_hr_rights()
        for req in self.filtered(lambda r: r.state == 'pending'):
            vals = {}
            for fname in (req.changed_field_names or '').split(','):
                if fname not in PRIVATE_FIELDS:
                    continue
                value = req[fname]
                vals[fname] = value.id if self._fields[fname].type == 'many2one' and value else (
                    value if self._fields[fname].type == 'integer' else (value or False))
            req.employee_id.write(vals)
            req.write({'state': 'approved', 'decided_by': self.env.user.id, 'decided_on': fields.Datetime.now()})
            req.employee_id.message_post(
                body=_("Private details updated through an approved Employee Self Service request."))
        return True

    def action_reject(self):
        self._check_hr_rights()
        for req in self.filtered(lambda r: r.state == 'pending'):
            if not (req.reject_reason or '').strip():
                raise UserError(_("Please write the rejection reason before rejecting."))
            req.write({'state': 'rejected', 'decided_by': self.env.user.id, 'decided_on': fields.Datetime.now()})
        return True