from datetime import datetime, time, timedelta

import pytz

from odoo import fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def _get_planning_timezone(self):
        """Return the timezone used for flexible Planning dates."""
        self.ensure_one()

        company_timezone = False
        if self.company_id and self.company_id.resource_calendar_id:
            company_timezone = self.company_id.resource_calendar_id.tz

        timezone_name = (
            self.tz
            or company_timezone
            or self.env.user.tz
            or 'UTC'
        )

        try:
            return pytz.timezone(timezone_name or 'UTC')
        except pytz.UnknownTimeZoneError:
            return pytz.UTC

    def _get_attendance_schedule_timezone(self):
        """
        Return the timezone used to interpret the employee's expected schedule.

        Dedicated employees follow the timezone of their resource.calendar.
        Fully-flexible employees follow their employee/company/user timezone.
        """
        self.ensure_one()

        if self.resource_calendar_id and self.resource_calendar_id.tz:
            try:
                return pytz.timezone(self.resource_calendar_id.tz)
            except pytz.UnknownTimeZoneError:
                pass

        return self._get_planning_timezone()

    def _planning_local_day_bounds_utc(self, check_date):
        self.ensure_one()
        timezone = self._get_planning_timezone()

        local_start = timezone.localize(datetime.combine(check_date, time.min))
        local_end = timezone.localize(
            datetime.combine(check_date + timedelta(days=1), time.min)
        )

        return (
            local_start.astimezone(pytz.UTC).replace(tzinfo=None),
            local_end.astimezone(pytz.UTC).replace(tzinfo=None),
        )

    def _get_planning_slots_for_date(self, check_date, published_only=True):
        """Return published Planning slots whose local start date is check_date."""
        self.ensure_one()

        if not check_date or not self.resource_id:
            return self.env['planning.slot']

        start_utc, end_utc = self._planning_local_day_bounds_utc(check_date)

        domain = [
            ('resource_id', '=', self.resource_id.id),
            ('start_datetime', '>=', start_utc),
            ('start_datetime', '<', end_utc),
        ]

        if published_only and 'state' in self.env['planning.slot']._fields:
            domain.append(('state', '=', 'published'))

        return self.env['planning.slot'].search(
            domain,
            order='start_datetime asc, id asc',
        )

    def _get_planning_slots_for_dates(
        self,
        start_date,
        end_date,
        published_only=True,
    ):
        """Return planned employee shifts whose local start date is in a date range."""
        self.ensure_one()

        if not start_date or not end_date or end_date < start_date:
            return self.env['planning.slot']

        if not self.resource_id:
            return self.env['planning.slot']

        start_utc, _ = self._planning_local_day_bounds_utc(start_date)
        _, end_utc = self._planning_local_day_bounds_utc(end_date)

        domain = [
            ('resource_id', '=', self.resource_id.id),
            ('start_datetime', '>=', start_utc),
            ('start_datetime', '<', end_utc),
        ]

        if published_only and 'state' in self.env['planning.slot']._fields:
            domain.append(('state', '=', 'published'))

        return self.env['planning.slot'].search(
            domain,
            order='start_datetime asc, id asc',
        )

    def _get_calendar_attendance_intervals_for_date(self, check_date):
        """
        Return logical working intervals from the employee's dedicated
        resource.calendar for a date.

        A dedicated working schedule may contain multiple calendar attendance
        rows because of lunch. For biometric attendance purposes, those rows
        represent one continuous shift window. Therefore we merge work
        intervals only when the gap is covered by an actual lunch interval
        from the same resource.calendar.

        Overnight calendar intervals are also merged when the following
        interval is an immediate midnight continuation.
        """
        self.ensure_one()

        calendar = self.resource_calendar_id
        resource = self.resource_id
        if not calendar or not resource or not check_date:
            return []

        timezone = self._get_attendance_schedule_timezone()

        local_start = timezone.localize(
            datetime.combine(check_date, time.min)
        )
        local_end = timezone.localize(
            datetime.combine(check_date + timedelta(days=2), time.min)
        )

        # Attendance intervals describe the employee's actual working
        # schedule. We query lunch separately so that we can merge only
        # lunch-separated work segments and preserve genuine split shifts.
        result = calendar._attendance_intervals_batch(
            local_start,
            local_end,
            resources=resource,
            tz=timezone,
        )
        intervals = result.get(resource.id, [])

        lunch_result = calendar._attendance_intervals_batch(
            local_start,
            local_end,
            resources=resource,
            tz=timezone,
            lunch=True,
        )
        lunch_intervals = lunch_result.get(resource.id, [])

        def normalize_intervals(raw_intervals):
            normalized = []
            for interval in raw_intervals:
                start = interval[0]
                end = interval[1]

                if not start or not end:
                    continue

                if not isinstance(start, datetime):
                    start = fields.Datetime.to_datetime(start)
                if not isinstance(end, datetime):
                    end = fields.Datetime.to_datetime(end)

                if not start or not end or end <= start:
                    continue

                if start.tzinfo is None:
                    start = timezone.localize(start)
                else:
                    start = start.astimezone(timezone)

                if end.tzinfo is None:
                    end = timezone.localize(end)
                else:
                    end = end.astimezone(timezone)

                normalized.append((start, end))

            normalized.sort(key=lambda item: (item[0], item[1]))
            return normalized

        normalized = normalize_intervals(intervals)
        normalized_lunch = normalize_intervals(lunch_intervals)

        if not normalized:
            return []

        midnight_gap = timedelta(minutes=2)

        # Merge same-day work intervals only when the gap is actually covered
        # by a lunch interval. This preserves genuine split shifts.
        logical_intervals = []

        for start, end in normalized:
            if not logical_intervals:
                logical_intervals.append([start, end])
                continue

            previous_start, previous_end = logical_intervals[-1]

            lunch_between = any(
                lunch_start <= previous_end
                and lunch_end >= start
                for lunch_start, lunch_end in normalized_lunch
            )

            # if (
            #     start.date() == previous_end.date()
            #     and lunch_between
            # ):
            #     logical_intervals[-1][1] = max(previous_end, end)
            # else:
            #     logical_intervals.append([start, end])

            is_contiguous = (
                    start.date() == previous_end.date()
                    and start == previous_end
            )

            if (
                    is_contiguous
                    or lunch_between
            ):
                logical_intervals[-1][1] = max(previous_end, end)
            else:
                logical_intervals.append([start, end])

        # An interval beginning at midnight can be the continuation of an
        # overnight shift from the previous local day. Do not treat that
        # continuation as a separate shift for the next day.
        previous_day_end = None
        previous_day_intervals = [
            interval
            for interval in logical_intervals
            if interval[0].date() == check_date - timedelta(days=1)
        ]
        if previous_day_intervals:
            previous_day_end = max(
                interval[1]
                for interval in previous_day_intervals
            )

        same_day = []
        for start, end in logical_intervals:
            if start.date() != check_date:
                continue

            if (
                previous_day_end
                and start.time() <= time(0, 2)
                and start - previous_day_end <= midnight_gap
            ):
                continue

            same_day.append((start, end))

        result_intervals = []

        for start, end in same_day:
            logical_end = end

            # Merge only an immediate continuation beginning on the following
            # local date. This covers Odoo's midnight split of an overnight
            # dedicated shift.
            for next_start, next_end in logical_intervals:
                if next_start.date() != check_date + timedelta(days=1):
                    continue

                if next_start < logical_end:
                    continue

                gap = next_start - logical_end
                if gap <= midnight_gap and next_start.time() <= time(0, 2):
                    logical_end = max(logical_end, next_end)
                break

            result_intervals.append({
                'source': 'calendar',
                'slot': False,
                'calendar': calendar,
                'name': (calendar.name or '').strip() or 'Working Schedule',
                'start_local': start,
                'end_local': logical_end,
                'start_utc': start.astimezone(pytz.UTC),
                'end_utc': logical_end.astimezone(pytz.UTC),
            })

        result_intervals.sort(key=lambda item: item['start_utc'])
        return result_intervals

    def _get_planning_attendance_intervals_for_date(
        self,
        check_date,
        published_only=True,
    ):
        """Return concrete published Planning slots as attendance intervals."""
        self.ensure_one()

        intervals = []
        slots = self._get_planning_slots_for_date(
            check_date,
            published_only=published_only,
        )

        timezone = self._get_planning_timezone()
        for slot in slots:
            start = fields.Datetime.to_datetime(slot.start_datetime)
            end = fields.Datetime.to_datetime(slot.end_datetime)

            if not start or not end or end <= start:
                continue

            if start.tzinfo is None:
                start_utc = pytz.UTC.localize(start)
            else:
                start_utc = start.astimezone(pytz.UTC)

            if end.tzinfo is None:
                end_utc = pytz.UTC.localize(end)
            else:
                end_utc = end.astimezone(pytz.UTC)

            intervals.append({
                'source': 'planning',
                'slot': slot,
                'calendar': getattr(slot, 'resource_calendar_id', False),
                'name': (
                    (slot.name or '').strip()
                    or (
                        slot.role_id.name.strip()
                        if getattr(slot, 'role_id', False) and slot.role_id.name
                        else 'Planned Shift'
                    )
                ),
                'start_local': start_utc.astimezone(timezone),
                'end_local': end_utc.astimezone(timezone),
                'start_utc': start_utc,
                'end_utc': end_utc,
            })

        intervals.sort(key=lambda item: (item['start_utc'], item['slot'].id))
        return intervals

    def _get_expected_attendance_intervals_for_date(
        self,
        check_date,
        published_only=True,
    ):
        """
        Return the expected attendance windows for this employee/date.

        Scheduling source is determined by the employee's Working Hours field:

        * resource_calendar_id set -> dedicated working schedule;
        * resource_calendar_id empty -> fully flexible, therefore Planning.
        """
        self.ensure_one()

        if self.resource_calendar_id:
            return self._get_calendar_attendance_intervals_for_date(check_date)

        return self._get_planning_attendance_intervals_for_date(
            check_date,
            published_only=published_only,
        )

    def _get_expected_attendance_intervals_for_dates(
        self,
        start_date,
        end_date,
        published_only=True,
    ):
        """Return expected attendance windows for every date in a range."""
        self.ensure_one()

        if not start_date or not end_date or end_date < start_date:
            return []

        intervals = []
        current_date = start_date
        while current_date <= end_date:
            intervals.extend(
                self._get_expected_attendance_intervals_for_date(
                    current_date,
                    published_only=published_only,
                )
            )
            current_date += timedelta(days=1)

        intervals.sort(key=lambda item: (item['start_utc'], item['slot'].id if item['slot'] else 0))
        return intervals
