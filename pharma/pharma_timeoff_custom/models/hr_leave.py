from datetime import date, timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    # =========================================================================
    # TIME OFF TYPE FIELDS
    # =========================================================================

    max_time_off = fields.Float(
        string='Max Time Off',
        default=0.0,
        help='Maximum total number of employee-selected leave days allowed '
             'for this type in a calendar month. Set to 0 for no restriction.'
    )

    cannot_be_combined_with_ids = fields.Many2many(
        'hr.leave.type',
        'hr_leave_type_combination_rel',
        'leave_type_id',
        'combined_leave_type_id',
        string='Cannot Be Combined With',
        help='Time off types that cannot be combined with this time off type.'
    )

    applied_before = fields.Integer(
        string='Days',
        default=0,
        help=(
            'Number of days after the actual leave date during which '
            'the employee can register a past leave. '
            'Set to 0 for no retrospective registration restriction.'
        ),
    )

    abbreviation = fields.Char(
        string='Abbreviations',
        help='Abbreviation used in attendance sheets for this time off type.'
    )

    # =========================================================================
    # FIELD VALIDATIONS
    # =========================================================================

    @api.constrains('max_time_off')
    def _check_max_time_off(self):
        for leave_type in self:
            if leave_type.max_time_off < 0:
                raise ValidationError(
                    'Max Time Off cannot be negative.'
                )

    @api.constrains('applied_before')
    def _check_applied_before(self):
        for leave_type in self:
            if leave_type.applied_before < 0:
                raise ValidationError(
                    'Days cannot be negative.'
                )

    


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    # =========================================================================
    # COMMON CUSTOM VALIDATION
    # =========================================================================
    def _check_custom_timeoff_rules(self):
        """
        Validate Pharma custom Time Off rules.

        The finalized attendance-period restriction applies to ALL users,
        including System Administrators.

        Other Pharma Time Off policy rules are still restricted to users
        belonging to the Time Off Constraints group.
        """

        for leave in self:

            if not leave.employee_id:
                continue

            if not leave.holiday_status_id:
                continue

            # Cancelled and refused leaves do not need validation.
            if leave.state in ('cancel', 'refuse'):
                continue

            # ================================================================
            # 1. FINALIZED ATTENDANCE LOCK
            # ================================================================

            if self.env.user.has_group(
                'pharma_timeoff_custom.group_timeoff_constraints'
            ):
                leave._check_finalized_attendance_period()


            # ================================================================
            # 2. OTHER PHARMA TIME-OFF RULES
            # ================================================================

            if not self.env.user.has_group(
                'pharma_timeoff_custom.group_timeoff_constraints'
            ):
                continue

            leave._check_leave_application_window()
            leave._check_cannot_be_combined()
            leave._check_leave_policy_rules()
            leave._check_max_time_off()
            
    def _check_finalized_attendance_period(self):
        """
        Prevent leave registration for dates belonging to an
        attendance period that has already been finalized.

        This restriction applies to ALL users, including
        System Administrators.
        """

        AttendanceSheet = self.env['pharma.attendance.sheet']

        for leave in self:

            if not leave.request_date_from:
                continue

            start_date = leave.request_date_from
            end_date = leave.request_date_to or start_date

            current_date = start_date

            while current_date <= end_date:

                finalized_sheet = AttendanceSheet.search(
                    [
                        ('date_from', '<=', current_date),
                        ('date_to', '>=', current_date),
                        ('state', '=', 'finalized'),
                    ],
                    limit=1,
                )

                if finalized_sheet:
                    raise ValidationError(
                        'Leave cannot be registered for '
                        f'{current_date.strftime("%d/%m/%Y")}.\n\n'
                        'The attendance sheet containing this date '
                        'has already been finalized.\n\n'
                        'Attendance period: '
                        f'{finalized_sheet.date_from.strftime("%d/%m/%Y")} '
                        'to '
                        f'{finalized_sheet.date_to.strftime("%d/%m/%Y")}.'
                    )

                current_date += timedelta(days=1)
    
    def _check_leave_application_window(self):
        """
        Validate retrospective leave registration.

        The 'Days' field on the Time Off Type defines how many days
        after the actual leave date an employee can register a past leave.

        Future leave is NOT restricted by this field.
        """

        today = fields.Date.context_today(self)

        for leave in self:

            if not leave.holiday_status_id:
                continue

            if not leave.request_date_from:
                continue

            start_date = leave.request_date_from
            end_date = leave.request_date_to or start_date

            allowed_days = leave.holiday_status_id.applied_before

            current_date = start_date

            while current_date <= end_date:

                # Future leave is not restricted by "Days"
                if current_date > today:
                    current_date += timedelta(days=1)
                    continue

                # 0 means no retrospective registration restriction.
                if allowed_days <= 0:
                    current_date += timedelta(days=1)
                    continue

                days_since_leave = (today - current_date).days

                if days_since_leave > allowed_days:
                    raise ValidationError(
                        'Leave for %s can no longer be registered.\n\n'
                        'The allowed registration window is %s day(s) '
                        'after the actual leave date.\n\n'
                        'Today: %s'
                        % (
                            current_date.strftime('%d/%m/%Y'),
                            allowed_days,
                            today.strftime('%d/%m/%Y'),
                        )
                    )

                current_date += timedelta(days=1)
    # =========================================================================
    # 2. CANNOT BE COMBINED WITH
    # =========================================================================

    def _check_cannot_be_combined(self):
        """
        Prevent a leave from being combined with a leave type configured
        in "Cannot Be Combined With".

        A combination is considered to exist when:

            - Leave periods overlap
            OR
            - One leave ends immediately before the other starts.
        """

        Leave = self.env['hr.leave']

        for leave in self:
            if not leave.employee_id:
                continue

            if not leave.holiday_status_id:
                continue

            prohibited_types = (
                leave.holiday_status_id.cannot_be_combined_with_ids
            )

            if not prohibited_types:
                continue

            if not leave.request_date_from:
                continue

            if not leave.request_date_to:
                continue

            existing_leaves = Leave.search([
                ('id', '!=', leave.id),
                ('employee_id', '=', leave.employee_id.id),
                ('holiday_status_id', 'in', prohibited_types.ids),
                ('state', 'not in', ['cancel', 'refuse']),

                # Existing leave starts before requested leave ends
                # plus one day.
                (
                    'request_date_from',
                    '<=',
                    leave.request_date_to + timedelta(days=1),
                ),

                # Existing leave ends after requested leave starts
                # minus one day.
                (
                    'request_date_to',
                    '>=',
                    leave.request_date_from - timedelta(days=1),
                ),
            ])

            if not existing_leaves:
                continue

            conflicting_leave = existing_leaves[0]

            raise ValidationError(
                f'This time off cannot be combined with '
                f'"{conflicting_leave.holiday_status_id.name}".\n\n'
                f'Existing '
                f'{conflicting_leave.holiday_status_id.name}: '
                f'{conflicting_leave.request_date_from.strftime("%d/%m/%Y")} '
                f'to '
                f'{conflicting_leave.request_date_to.strftime("%d/%m/%Y")}\n'
                f'Requested '
                f'{leave.holiday_status_id.name}: '
                f'{leave.request_date_from.strftime("%d/%m/%Y")} '
                f'to '
                f'{leave.request_date_to.strftime("%d/%m/%Y")}'
            )

    # =========================================================================
    # 3. CLIENT LEAVE POLICY RULES
    # =========================================================================

    @staticmethod
    def _get_policy_leave_code(leave_type):
        """
        Return the client policy code for a leave type.

        The preferred source is the custom "Abbreviations" field.
        The leave type name is used as a fallback.
        """
        if not leave_type:
            return ''

        abbreviation = (leave_type.abbreviation or '').strip().upper()
        normalized = (
            abbreviation
            .replace(' ', '')
            .replace('_', '-')
        )

        if normalized:
            if normalized == 'CL':
                return 'CL'
            if normalized == 'SL':
                return 'SL'
            if normalized == 'EL':
                return 'EL'
            if normalized in ('COFF', 'C-OFF'):
                return 'C-OFF'
            if normalized in ('SHORT', 'SHORTLEAVE', 'SH'):
                return 'SHORT'

        name = (leave_type.name or '').strip().lower()

        if 'casual leave' in name or name == 'cl':
            return 'CL'
        if 'sick leave' in name or name == 'sl':
            return 'SL'
        if 'earned leave' in name or name == 'el':
            return 'EL'
        if 'short leave' in name:
            return 'SHORT'
        if 'compensatory off' in name or 'c-off' in name or name == 'coff':
            return 'C-OFF'

        return ''

    @staticmethod
    def _get_calendar_leave_days(leave):
        """
        Return the calendar-day span selected by the employee.

        This is used for consecutive-day rules. It intentionally includes
        weekends because "consecutive days" is a calendar concept.
        """
        if not leave.request_date_from or not leave.request_date_to:
            return 0

        if leave.request_date_to < leave.request_date_from:
            return 0

        return (
            leave.request_date_to - leave.request_date_from
        ).days + 1

    def _check_leave_policy_rules(self):
        """
        Apply the unambiguous leave-duration rules from the client policy.

        Client policy:
            CL:
                - minimum 0.5 day
                - maximum 2 consecutive days

            SL:
                - minimum 0.5 day
                - maximum 2 days at a time

            EL:
                - minimum 1 day

        The client document also says that SL beyond 2 consecutive days
        requires a medical certificate, while the revised summary says
        SL has a maximum of 2 days at a time. Those statements conflict,
        so this code enforces the explicit maximum of 2 days and does not
        invent an exception.

        Attendance-based rules such as 9h20 full day, 4h45 half day and
        7h30 Short Leave are handled by attendance/status logic rather
        than by leave-request validation.
        """
        for leave in self:
            if not leave.employee_id or not leave.holiday_status_id:
                continue

            if leave.state in ('cancel', 'refuse'):
                continue

            policy_code = self._get_policy_leave_code(
                leave.holiday_status_id
            )

            if not policy_code:
                continue

            number_of_days = leave.number_of_days or 0.0
            calendar_days = self._get_calendar_leave_days(leave)

            # Casual Leave
            if policy_code == 'CL':
                if number_of_days < 0.5:
                    raise ValidationError(
                        'Casual Leave (CL) must be at least 0.5 day.'
                    )

                if calendar_days > 2:
                    raise ValidationError(
                        'Casual Leave (CL) cannot be applied for more '
                        'than 2 consecutive days.'
                    )

            # Sick Leave
            elif policy_code == 'SL':
                if number_of_days < 0.5:
                    raise ValidationError(
                        'Sick Leave (SL) must be at least 0.5 day.'
                    )

                if calendar_days > 2 and not leave.supported_attachment_ids:
                    raise ValidationError(
                        'A medical certificate is required for Sick Leave '
                        'exceeding 2 consecutive days. Please upload the '
                        'medical certificate in the Supporting Document field.'
                    )

            # Earned Leave
            elif policy_code == 'EL':
                if number_of_days < 1.0:
                    raise ValidationError(
                        'Earned Leave (EL) must be at least 1 full day.'
                    )

    # =========================================================================
    # 4. EXPECTED WORK SCHEDULE
    # =========================================================================

    @classmethod
    def _get_employee_planning_slots(cls, employee, check_date):
        """
        Return Planning slots for the employee/date.

        Planning is the authoritative schedule source for this customization.
        """
        if not employee or not check_date:
            return employee.env['planning.slot'] if employee else False

        return employee._get_planning_slots_for_date(
            check_date,
            published_only=True,
        )

    @classmethod
    def _is_employee_working_day(cls, employee, check_date):
        """
        Return True when the employee has an expected work interval.

        Planning slots are the authoritative expected-work source.
        """
        if not employee or not check_date:
            return False

        return bool(
            employee._get_expected_attendance_intervals_for_date(
                check_date,
                published_only=True,
            )
        )

    # =========================================================================
    # 5. MONTHLY EMPLOYEE-SELECTED LEAVE DAYS
    # =========================================================================

    @classmethod
    def _get_monthly_working_days(cls, employee, start_date, end_date):
        """
        Calculate employee-selected leave days that count toward the
        monthly Max Time Off limit.

        The calculation is employee-specific. Dedicated employees use their
        resource.calendar Working Hours; fully-flexible employees use published
        Odoo Planning slots. A calendar date counts once when at least one
        expected work interval exists for the employee on that date.

        IMPORTANT:

            This method does NOT calculate sandwich entitlement.

            It only counts dates inside the employee's selected leave range
            on which that employee is scheduled to work.

            Therefore, a non-working Saturday/Sunday is not counted merely
            because it falls inside a leave request.

            A working Saturday IS counted when the employee's Working Hours or
            Planning schedule says that Saturday is a working day.

        Examples:

            Monday-Friday
                = 5 scheduled working days

            Friday-Monday in a week where Saturday is non-working
                = 2 scheduled working days

            Friday-Monday in a week where Saturday is working
                = 3 scheduled working days

            Sunday only
                = 0 scheduled working days
        """
        if not employee or not start_date or not end_date:
            return 0.0

        if end_date < start_date:
            return 0.0

        working_days = 0
        current_date = start_date

        while current_date <= end_date:
            if cls._is_employee_working_day(employee, current_date):
                working_days += 1

            current_date += timedelta(days=1)

        return float(working_days)


    # =========================================================================
    # 6. MAX TIME OFF PER MONTH
    # =========================================================================

    def _check_max_time_off(self):
        """
        Validate the maximum TOTAL NUMBER OF EMPLOYEE-SELECTED
        LEAVE DAYS allowed for a Time Off Type in a calendar month.

        IMPORTANT:

            Max Time Off = 2 means maximum 2 leave days in the month.

            It does NOT mean maximum 2 leave requests.

            It also does NOT count sandwich weekend days toward
            the monthly limit.

        Examples:

            Max Time Off = 2

            Leave 1 = 1 day
            Leave 2 = 1 day

            Total = 2 days
            Result -> Allowed

            Max Time Off = 2

            Existing = 2 days
            New request = 1 day

            Total = 3 days
            Result -> Rejected

            Friday-Monday:

            Friday  = 1
            Saturday = 0
            Sunday = 0
            Monday = 1

            Total = 2 days

            Result -> Allowed
        """

        Leave = self.env['hr.leave']

        for leave in self:
            max_time_off = leave.holiday_status_id.max_time_off

            # Client-policy defaults when Max Time Off is left at 0:
            #   CL       -> 2 days/month
            #   Short    -> 1 entitlement/month
            #   C-Off    -> 2 days/month
            #
            # A positive Max Time Off configured on the Time Off Type
            # overrides these defaults.
            policy_code = self._get_policy_leave_code(
                leave.holiday_status_id
            )

            if not max_time_off:
                policy_defaults = {
                    'CL': 2.0,
                    'SHORT': 1.0,
                    'C-OFF': 2.0,
                }
                max_time_off = policy_defaults.get(policy_code, 0.0)

            # 0 means no monthly restriction.
            if not max_time_off:
                continue

            if not leave.employee_id:
                continue

            if not leave.request_date_from:
                continue

            if not leave.request_date_to:
                continue

            # -------------------------------------------------------------
            # Determine the month of the requested leave.
            # -------------------------------------------------------------

            month_start = leave.request_date_from.replace(day=1)

            if month_start.month == 12:
                next_month = date(
                    month_start.year + 1,
                    1,
                    1,
                )
            else:
                next_month = date(
                    month_start.year,
                    month_start.month + 1,
                    1,
                )

            month_end = next_month - timedelta(days=1)

            # -------------------------------------------------------------
            # Find existing leaves for:
            #
            #   - Same employee
            #   - Same Time Off Type
            #   - Leave period overlaps this month
            #
            # Cancelled/refused leaves are ignored.
            # -------------------------------------------------------------

            existing_leaves = Leave.search([
                ('id', '!=', leave.id),
                ('employee_id', '=', leave.employee_id.id),
                ('holiday_status_id', '=', leave.holiday_status_id.id),
                ('state', 'not in', ['cancel', 'refuse']),

                # Existing leave starts before month ends.
                (
                    'request_date_from',
                    '<=',
                    month_end,
                ),

                # Existing leave ends after month starts.
                (
                    'request_date_to',
                    '>=',
                    month_start,
                ),
            ])

            # -------------------------------------------------------------
            # Calculate existing employee-selected leave days.
            # -------------------------------------------------------------

            existing_days = 0.0

            for existing_leave in existing_leaves:

                if (
                    not existing_leave.request_date_from
                    or not existing_leave.request_date_to
                ):
                    continue

                existing_start = max(
                    existing_leave.request_date_from,
                    month_start,
                )

                existing_end = min(
                    existing_leave.request_date_to,
                    month_end,
                )

                if existing_start > existing_end:
                    continue

                existing_days += self._get_monthly_working_days(
                    leave.employee_id,
                    existing_start,
                    existing_end,
                )

            # -------------------------------------------------------------
            # Calculate employee-selected days for CURRENT request.
            # -------------------------------------------------------------

            current_start = max(
                leave.request_date_from,
                month_start,
            )

            current_end = min(
                leave.request_date_to,
                month_end,
            )

            current_days = self._get_monthly_working_days(
                leave.employee_id,
                current_start,
                current_end,
            )

            # -------------------------------------------------------------
            # Total monthly employee-selected leave days.
            # -------------------------------------------------------------

            total_days = existing_days + current_days

            # -------------------------------------------------------------
            # Validate monthly limit.
            # -------------------------------------------------------------

            if total_days > max_time_off:

                month_name = leave.request_date_from.strftime('%B %Y')

                raise ValidationError(
                    f'Maximum Time Off limit exceeded for '
                    f'"{leave.holiday_status_id.name}".\n\n'
                    f'Month: {month_name}\n'
                    f'Maximum allowed: {max_time_off:.2f} leave day(s)\n'
                    f'Already applied: {existing_days:.2f} leave day(s)\n'
                    f'This request: {current_days:.2f} leave day(s)\n\n'
                    f'You cannot apply for this leave because the '
                    f'monthly limit would be exceeded.'
                )

    # =========================================================================
    # 7. ORM CREATE
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        """
        Create the leave first so Odoo can populate its standard fields,
        then run the Pharma validations.
        """

        leaves = super().create(vals_list)

        leaves._check_custom_timeoff_rules()

        return leaves

    # =========================================================================
    # 8. ORM WRITE
    # =========================================================================

    def write(self, vals):
        """
        Re-check Pharma rules when actual user-editable leave information
        changes.

        IMPORTANT:

            Odoo internally writes calculated/workflow fields while
            processing a leave.

            We therefore DO NOT trigger our validations for:

                - date_from
                - date_to
                - number_of_days
                - number_of_hours

            This prevents Odoo's internal workflow from accidentally
            validating the wrong state/record again.
        """

        result = super().write(vals)

        # If approval/validation is already running, do not run the
        # validation again because Odoo may perform internal writes.
        if self.env.context.get('skip_pharma_timeoff_validation'):
            return result

        fields_to_check = {
            'holiday_status_id',
            'employee_id',
            'request_date_from',
            'request_date_to',
        }

        if fields_to_check.intersection(vals.keys()):
            self._check_custom_timeoff_rules()

        return result

    # =========================================================================
    # 9. APPROVAL
    # =========================================================================

    def action_approve(self, check_state=True):
        """
        Validate only the leave records being approved.

        After our validation succeeds, pass a context flag to the
        standard Odoo workflow so internal writes do not trigger our
        custom validation again.
        """

        if not self.env.context.get('skip_pharma_timeoff_validation'):
            for leave in self:
                leave._check_custom_timeoff_rules()

        return super(
            HrLeave,
            self.with_context(
                skip_pharma_timeoff_validation=True
            )
        ).action_approve(check_state=check_state)

    # =========================================================================
    # 10. FINAL VALIDATION / APPROVAL
    # =========================================================================

    def action_validate(self, check_state=True):
        """
        Validate only the leave records being finally approved.

        The check_state parameter is required because Odoo 18 and
        other inherited modules such as Payroll may call:

            action_validate(check_state=True)
        """

        if not self.env.context.get('skip_pharma_timeoff_validation'):
            for leave in self:
                leave._check_custom_timeoff_rules()

        return super(
            HrLeave,
            self.with_context(
                skip_pharma_timeoff_validation=True
            )
        ).action_validate(check_state=check_state)