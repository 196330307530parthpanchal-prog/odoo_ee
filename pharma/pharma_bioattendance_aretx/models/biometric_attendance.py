import base64
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from io import BytesIO
import pytz
from openpyxl import load_workbook
from odoo import fields, models, _, api
from odoo.exceptions import UserError

# ------------------------------------------------------------------------
# LOGGING
# -------------------------------------------------------------------------
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)


class PharmaBiometricAttendance(models.Model):
    _name = "pharma.biometric.attendance"
    _description = "Biometric Attendance Import"
    _order = "id desc"
    name = fields.Char(
        string="Reference",
        required=True,
        default=lambda self: _("New"),
        copy=False,
    )
    file = fields.Binary(
        string="Excel File",
        required=False,
        attachment=True,
    )
    filename = fields.Char(
        string="File Name",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("imported", "Imported"),
            ("processed", "Processed"),
        ],
        string="Status",
        default="draft",
        readonly=True,
    )
    total_records = fields.Integer(
        string="Total Punches",
        readonly=True,
    )
    attendance_created = fields.Integer(
        string="Attendances Created",
        readonly=True,
    )
    unmatched_employees = fields.Integer(
        string="Unmatched Employees",
        readonly=True,
    )
    unmatched_punches = fields.Integer(
        string="Unmatched Punches",
        readonly=True,
    )

    def _to_utc_naive(self, dt):
        """
        Normalize a datetime to UTC-naive.
        Odoo stores/manages Datetime values as UTC-naive internally.
        This prevents comparisons between timezone-aware and timezone-naive
        datetime objects.
        """
        if not dt:
            return dt
        if dt.tzinfo is not None:
            dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
        return dt

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.filename:
                record.name = record.filename
            _logger.info(
                "BIOMETRIC IMPORT CREATED | ID=%s | Name=%s | File=%s",
                record.id,
                record.name,
                record.filename or "N/A",
            )
        return records

    # ------------------------------------------------------------------------
    #   UPLOAD BUTTON
    # -------------------------------------------------------------------------
    def action_upload_data(self):
        _logger.info(
            "🚀 PROCESS BUTTON CLICKED | Import IDs=%s",
            self.ids,
        )
        for record in self:
            
            if record.state == "processed":
                raise UserError(
                    _('The file "%s" has already been processed.')
                    % (record.filename or record.name)
                )
            record._process_file()
        return True

    # -------------------------------------------------------------------------
    # READ EXCEL FILE
    # -------------------------------------------------------------------------
    def _process_file(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_("Please upload an Excel file first."))
        # ---------------------------------------------------------------------
        # Decode Excel file
        # ---------------------------------------------------------------------
        try:
            file_data = base64.b64decode(self.file)
            workbook = load_workbook(
                filename=BytesIO(file_data),
                data_only=True,
            )
        except Exception as error:
            raise UserError(_("Unable to read the Excel file.\n\n%s") % error)
        # ---------------------------------------------------------------------
        # Get active worksheet
        # ---------------------------------------------------------------------
        worksheet = workbook.active
        rows = list(worksheet.iter_rows(values_only=True))
        if not rows:
            raise UserError(_("The Excel file is empty."))
        # ---------------------------------------------------------------------
        # Read headers
        #
        # IMPORTANT:
        # "No" is intentionally NOT used.
        # Only EnNo and DateTime are required.
        # ---------------------------------------------------------------------
        headers = [str(value).strip() if value is not None else "" for value in rows[0]]
        _logger.info(
            "📋 EXCEL HEADERS | %s",
            headers,
        )
        _logger.info(
            "🚫 'No' COLUMN WILL BE IGNORED | Using EnNo + DateTime only",
        )
        try:
            enno_index = headers.index("EnNo")
            datetime_index = headers.index("DateTime")
            _logger.info(
                "🔎 COLUMN MAPPING | EnNo index=%s | DateTime index=%s",
                enno_index,
                datetime_index,
            )
        except ValueError:
            _logger.error(
                "❌ REQUIRED COLUMNS NOT FOUND | Headers=%s",
                headers,
            )
            raise UserError(
                _("The Excel file must contain " '"EnNo" and "DateTime" columns.')
            )
        # ---------------------------------------------------------------------
        # Read biometric punches
        # --------------------------------------------------------------------
        punches = []
        skipped_empty_employee = 0
        skipped_empty_datetime = 0
        _logger.info(
            "🔄 STARTING BIOMETRIC PUNCH EXTRACTION | Data rows=%s",
            max(len(rows) - 1, 0),
        )
        for row_number, row in enumerate(
            rows[1:],
            start=2,
        ):
            if not row:
                _logger.debug(
                    "⏭️ SKIPPING EMPTY ROW | Excel row=%s",
                    row_number,
                )
                continue
            # -----------------------------------------------------------------
            # No column is deliberately ignored.
            # -----------------------------------------------------------------
            enno = row[enno_index]
            punch_datetime = row[datetime_index]
            # Ignore rows without employee number.
            if enno in (None, ""):
                skipped_empty_employee += 1
                _logger.debug(
                    "⏭️ SKIPPING ROW WITHOUT EnNo | Excel row=%s",
                    row_number,
                )
                continue
            # Ignore rows without DateTime.
            if punch_datetime in (None, ""):
                skipped_empty_datetime += 1
                _logger.debug(
                    "⏭️ SKIPPING ROW WITHOUT DateTime | " "Excel row=%s | EnNo=%s",
                    row_number,
                    enno,
                )
                continue
            punch_datetime = self._parse_datetime(
                punch_datetime,
                row_number,
            )
            normalized_enno = self._normalize_employee_number(enno)
            punches.append(
                {
                    "enno": normalized_enno,
                    "datetime": punch_datetime,
                }
            )
        
        if not punches:
            raise UserError(_("No valid biometric records were found."))
        # ---------------------------------------------------------------------
        # Create Biometric Attendance Logs
        # ---------------------------------------------------------------------
        log_model = self.env["biometric.attendance.log"]

        log_values = []
        unmatched_employee_ids = set()
        unmatched_punches = 0

        for punch in punches:
            biometric_user_id = punch["enno"]
            punch_time = punch["datetime"]

            employee = self.env["hr.employee"].search(
                [("barcode", "=", biometric_user_id)],
                limit=1,
            )

            if not employee:
                unmatched_employee_ids.add(biometric_user_id)
                unmatched_punches += 1

            log_values.append(
                {
                    "employee_id": employee.id if employee else False,
                    "employee_name": employee.name if employee else biometric_user_id,
                    "biometric_user_id": biometric_user_id,
                    "attendance_date": punch_time.date(),
                    "punch_time": punch_time,
                    "state": "imported",
                }
            )

        if log_values:
            log_model.create(log_values)

        # Upload Data only imports the punches into Attendance Logs.
        # It does NOT create hr.attendance records yet; that is done by
        # the Attendance Logs Process action. Therefore Attendances Created
        # must remain zero at this stage.
        self.write(
            {
                "state": "imported",
                "total_records": len(punches),
                "attendance_created": 0,
                "unmatched_employees": len(unmatched_employee_ids),
                "unmatched_punches": unmatched_punches,
            }
        )

        _logger.info(
            "BIOMETRIC ATTENDANCE LOGS CREATED | Import ID=%s | "
            "Count=%s | Unmatched Employees=%s | Unmatched Punches=%s | "
            "State=imported",
            self.id,
            len(log_values),
            len(unmatched_employee_ids),
            unmatched_punches,
        )

    # -------------------------------------------------------------------------
    # NORMALIZE EMPLOYEE NUMBER
    # -------------------------------------------------------------------------
    def _normalize_employee_number(self, value):
        """
        Normalize the biometric employee number so that numeric Excel
        values match the value stored in hr.employee.
        Examples:
            1007.0   -> '1007'
            1572.0   -> '1572'
            1701     -> '1701'
            '1007'   -> '1007'
            ' 1007 ' -> '1007'
        """
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
        if isinstance(value, int):
            return str(value)
        return str(value).strip()

    # -------------------------------------------------------------------------
    # PARSE DATE/TIME
    # -------------------------------------------------------------------------
    def _parse_datetime(self, value, row_number):
        _logger.debug(
            "🕐 PARSING DATETIME | Excel row=%s | Raw value=%r | Type=%s",
            row_number,
            value,
            type(value).__name__,
        )
        # Excel normally returns actual datetime objects.
        if isinstance(value, datetime):
            _logger.debug(
                "✅ DATETIME ALREADY PARSED BY OPENPYXL | " "row=%s | value=%s",
                row_number,
                value,
            )
            return value
        # Handle Excel values stored as text.
        if isinstance(value, str):
            value = value.strip()
            formats = [
                "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y %H:%M",
                "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M",
            ]
            for date_format in formats:
                try:
                    parsed_datetime = datetime.strptime(
                        value,
                        date_format,
                    )
                    _logger.debug(
                        "✅ DATETIME PARSED FROM TEXT | "
                        "row=%s | format=%s | value=%s",
                        row_number,
                        date_format,
                        parsed_datetime,
                    )
                    return parsed_datetime
                except ValueError:
                    continue
        _logger.error(
            "❌ INVALID DATETIME | Excel row=%s | value=%r",
            row_number,
            value,
        )
        raise UserError(
            _("Invalid DateTime value on Excel row %s:\n%s")
            % (
                row_number,
                value,
            )
        )

    # -------------------------------------------------------------------------
    # CONVERT LOCAL TIME TO UTC
    # -------------------------------------------------------------------------
    def _convert_to_utc(self, local_datetime):
        """
        Convert the biometric timestamp to the UTC-naive datetime format used
        internally by Odoo.
        Naive Excel timestamps are assumed to be in the current Odoo user's
        timezone. Already-aware timestamps are converted directly to UTC.
        """
        if not local_datetime:
            return local_datetime
        _logger.debug(
            "TIMEZONE CONVERSION START | Local=%s | tzinfo=%s",
            local_datetime,
            getattr(local_datetime, "tzinfo", None),
        )
        # If the value is already timezone-aware, do not localize it again.
        if local_datetime.tzinfo is not None:
            utc_datetime = local_datetime.astimezone(pytz.UTC)
            result = utc_datetime.replace(tzinfo=None)
            _logger.debug(
                "TIMEZONE CONVERSION RESULT | Aware Local=%s | UTC=%s",
                local_datetime,
                result,
            )
            return result
        timezone_name = self.env.user.tz or "UTC"
        try:
            timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "UNKNOWN TIMEZONE %s | Falling back to UTC",
                timezone_name,
            )
            timezone = pytz.UTC
        localized_datetime = timezone.localize(
            local_datetime,
            is_dst=None,
        )
        utc_datetime = localized_datetime.astimezone(pytz.UTC)
        result = utc_datetime.replace(tzinfo=None)
        _logger.debug(
            "TIMEZONE CONVERSION RESULT | Local=%s | Timezone=%s | UTC=%s",
            local_datetime,
            timezone_name,
            result,
        )
        return result

    # def _prepare_shift_attendance_values(self, employee, punch_times):
    #     """
    #     Convert one employee's biometric punches into hr.attendance records.
    #     IMPORTANT:
    #     The old implementation paired punches globally:
    #         1st -> IN
    #         2nd -> OUT
    #         3rd -> IN
    #         4th -> OUT
    #         ...
    #     That causes a single missing punch to shift every subsequent punch.
    #     New behaviour:
    #         - Normal attendance is paired within the same local date.
    #         - A punch from one date is NOT used as the checkout of another date.
    #         - Overnight punches are supported for night shifts such as:
    #             22:00 -> 06:30 next day.
    #         - An unmatched normal-day punch becomes a mispunch.
    #         - A mispunch does not affect the pairing of the following day.

    #     Returns:
    #         (attendance_values, mispunch_values, unmatched_punches)
    #     """

    #     self.ensure_one()
    #     if not employee or not punch_times:
    #         return [], [], 0
    #     # -------------------------------------------------------------
    #     # REMOVE EXACT DUPLICATES
    #     # -------------------------------------------------------------
    #     punch_times = sorted(set(punch_times))
    #     if not punch_times:
    #         return [], [], 0
    #     # -------------------------------------------------------------
    #     # EMPLOYEE TIMEZONE
    #     # -------------------------------------------------------------
    #     timezone = self._get_attendance_schedule_timezone(employee)
    #     # Convert all biometric punches to employee-local naive datetimes.
    #     #
    #     # We do the pairing in local time because attendance dates are
    #     # based on the employee's working date, not UTC date.
    #     local_punches = []
    #     for punch in punch_times:
    #         if punch.tzinfo is None:
    #             # Excel punches are local biometric times.
    #             local_punch = punch
    #         else:
    #             local_punch = punch.astimezone(timezone).replace(tzinfo=None)

    #         local_punches.append(local_punch)
    #     local_punches.sort()
    #     # -------------------------------------------------------------
    #     # GROUP PUNCHES BY LOCAL DATE
    #     # -------------------------------------------------------------

    #     punches_by_date = defaultdict(list)

    #     for punch in local_punches:
    #         punches_by_date[punch.date()].append(punch)

    #     sorted_dates = sorted(punches_by_date.keys())

    #     # -------------------------------------------------------------
    #     # RESULT CONTAINERS
    #     # -------------------------------------------------------------

    #     attendance_values = []
    #     mispunch_values = []

    #     # Punches which are consumed as part of an overnight pair.
    #     consumed_punches = set()

    #     # -------------------------------------------------------------
    #     # OVERNIGHT SHIFT DETECTION
    #     # -------------------------------------------------------------

    #     def is_plausible_overnight_pair(check_in, check_out):
    #         """
    #         Determine whether two punches on consecutive dates can
    #         reasonably represent an overnight shift.
    #         Example:
    #             26 Oct 22:03 -> 27 Oct 06:29

    #         MUST be accepted.
    #         Example:
    #             26 Oct 09:02 -> 27 Oct 09:01
    #         MUST NOT be accepted.
    #         This is deliberately conservative so that a normal-day
    #         mispunch can never consume the next day's first punch.
    #         """

    #         if not check_in or not check_out:
    #             return False

    #         if check_out.date() <= check_in.date():
    #             return False

    #         # Only consecutive dates can form an overnight attendance.
    #         if check_out.date() != check_in.date() + timedelta(days=1):
    #             return False

    #         # Night-shift check-in must occur late in the evening.
    #         #
    #         # Your Shift C is 22:00 - 06:30.
    #         # 18:00 is used as a safe lower boundary to allow
    #         # reasonable early/late biometric punches.
    #         if check_in.time() < datetime.strptime("18:00", "%H:%M").time():
    #             return False

    #         # Overnight checkout must occur in the morning.
    #         #
    #         # A 12:00 boundary prevents something like:
    #         #
    #         # 26 Oct 09:00 -> 27 Oct 09:00
    #         #
    #         # from being treated as an overnight pair.
    #         if check_out.time() > datetime.strptime("12:00", "%H:%M").time():
    #             return False

    #         duration = check_out - check_in

    #         # Maximum reasonable overnight attendance duration.
    #         #
    #         # Shift C is 8.5 hours, but we allow considerable tolerance
    #         # for biometric/attendance irregularities.
    #         if duration <= timedelta(0):
    #             return False

    #         if duration > timedelta(hours=14):
    #             return False

    #         return True

    #     # -------------------------------------------------------------
    #     # CREATE ATTENDANCE VALUE
    #     # -------------------------------------------------------------

    #     def make_attendance(
    #         check_in_local,
    #         check_out_local,
    #         is_mispunch=False,
    #         mispunch_reason=False,
    #     ):
    #         check_in_utc = self._convert_to_utc(check_in_local)

    #         if check_out_local:
    #             check_out_utc = self._convert_to_utc(check_out_local)
    #         else:
    #             check_out_utc = check_in_utc

    #         values = {
    #             "employee_id": employee.id,
    #             "check_in": check_in_utc,
    #             "check_out": check_out_utc,
    #             "shift_calendar_id": False,
    #             "is_mispunch": is_mispunch,
    #             "mispunch_reason": mispunch_reason or False,
    #             "in_mode": "technical",
    #             "out_mode": "technical",
    #         }

    #         return values

    #     # -------------------------------------------------------------
    #     # PROCESS EACH DAY INDEPENDENTLY
    #     # -------------------------------------------------------------

    #     for date_index, current_date in enumerate(sorted_dates):

    #         current_punches = punches_by_date[current_date]

    #         # Remove punches already consumed by an overnight pair.
    #         current_punches = [
    #             punch for punch in current_punches if punch not in consumed_punches
    #         ]

    #         if not current_punches:
    #             continue

    #         _logger.info(
    #             "DATE-AWARE PUNCH PROCESSING | Employee=%s | Date=%s | " "Punches=%s",
    #             employee.name,
    #             current_date,
    #             len(current_punches),
    #         )

    #         index = 0

    #         # ---------------------------------------------------------
    #         # PAIR SAME-DAY PUNCHES
    #         # ---------------------------------------------------------

    #         while index + 1 < len(current_punches):

    #             check_in_local = current_punches[index]
    #             check_out_local = current_punches[index + 1]

    #             # Same-day pair.
    #             #
    #             # Since the list is chronological, the checkout must
    #             # occur after the check-in.
    #             if check_out_local > check_in_local:

    #                 attendance_values.append(
    #                     make_attendance(
    #                         check_in_local,
    #                         check_out_local,
    #                         is_mispunch=False,
    #                     )
    #                 )

    #                 _logger.info(
    #                     "BIOMETRIC SAME-DAY PAIR | Employee=%s | " "IN=%s | OUT=%s",
    #                     employee.name,
    #                     check_in_local,
    #                     check_out_local,
    #                 )

    #                 index += 2
    #                 continue

    #             # Defensive fallback.
    #             #
    #             # This should practically never happen because punches
    #             # are sorted and duplicates were removed.
    #             reason = "Biometric punches are not in a valid chronological " "order."

    #             attendance_values.append(
    #                 make_attendance(
    #                     check_in_local,
    #                     None,
    #                     is_mispunch=True,
    #                     mispunch_reason=reason,
    #                 )
    #             )

    #             mispunch_values.append(
    #                 {
    #                     "employee_id": employee.id,
    #                     "punch_datetime": self._convert_to_utc(check_in_local),
    #                     "punch_type": "missing_out",
    #                     "reason": reason,
    #                     "state": "detected",
    #                 }
    #             )

    #             _logger.warning(
    #                 "BIOMETRIC INVALID PUNCH ORDER | Employee=%s | " "IN=%s",
    #                 employee.name,
    #                 check_in_local,
    #             )

    #             index += 1

    #         # ---------------------------------------------------------
    #         # HANDLE LAST UNPAIRED PUNCH OF THE DAY
    #         # ---------------------------------------------------------

    #         if index < len(current_punches):

    #             check_in_local = current_punches[index]

    #             # -----------------------------------------------------
    #             # TRY OVERNIGHT SHIFT PAIRING
    #             # -----------------------------------------------------

    #             next_date = current_date + timedelta(days=1)

    #             next_day_punches = punches_by_date.get(
    #                 next_date,
    #                 [],
    #             )

    #             # Find the first unused punch of the next day.
    #             next_day_punch = None

    #             for candidate in next_day_punches:
    #                 if candidate not in consumed_punches:
    #                     next_day_punch = candidate
    #                     break

    #             if next_day_punch and is_plausible_overnight_pair(
    #                 check_in_local,
    #                 next_day_punch,
    #             ):
    #                 attendance_values.append(
    #                     make_attendance(
    #                         check_in_local,
    #                         next_day_punch,
    #                         is_mispunch=False,
    #                     )
    #                 )

    #                 consumed_punches.add(next_day_punch)

    #                 _logger.info(
    #                     "BIOMETRIC OVERNIGHT PAIR | Employee=%s | " "IN=%s | OUT=%s",
    #                     employee.name,
    #                     check_in_local,
    #                     next_day_punch,
    #                 )

    #             else:
    #                 # -------------------------------------------------
    #                 # REAL MIS-PUNCH
    #                 # -------------------------------------------------

    #                 reason = (
    #                     "Biometric punch has no matching check-out "
    #                     "for the same attendance day."
    #                 )

    #                 attendance_values.append(
    #                     make_attendance(
    #                         check_in_local,
    #                         None,
    #                         is_mispunch=True,
    #                         mispunch_reason=reason,
    #                     )
    #                 )

    #                 mispunch_values.append(
    #                     {
    #                         "employee_id": employee.id,
    #                         "punch_datetime": self._convert_to_utc(check_in_local),
    #                         "punch_type": "missing_out",
    #                         "reason": reason,
    #                         "state": "detected",
    #                     }
    #                 )

    #                 _logger.warning(
    #                     "BIOMETRIC MIS-PUNCH | Employee=%s | "
    #                     "Date=%s | IN=%s | No valid checkout found",
    #                     employee.name,
    #                     current_date,
    #                     check_in_local,
    #                 )

    #     return attendance_values, mispunch_values, 0

    def _prepare_shift_attendance_values(self, employee, punch_times):
        """
        Prepare biometric attendance values using local calendar-day pairing.

        Rules:
        - First punch of a calendar day = CHECK IN.
        - Second punch of the same calendar day = CHECK OUT.
        - Third punch of the same day = new CHECK IN.
        - Fourth punch of the same day = CHECK OUT.
        - An unmatched final punch remains OPEN.
        - Never create CHECK OUT = CHECK IN.
        - Punches from another calendar day are NOT used as checkout.
        - Night-shift / overnight pairing is intentionally not handled here.
        """

        self.ensure_one()

        if not employee or not punch_times:
            return [], [], 0

        # -------------------------------------------------------------
        # REMOVE EXACT DUPLICATES
        # -------------------------------------------------------------
        punch_times = sorted(set(punch_times))

        if not punch_times:
            return [], [], 0

        # -------------------------------------------------------------
        # EMPLOYEE TIMEZONE
        # -------------------------------------------------------------
        timezone = self._get_attendance_schedule_timezone(employee)

        # -------------------------------------------------------------
        # CONVERT PUNCHES TO EMPLOYEE LOCAL TIME
        # -------------------------------------------------------------
        local_punches = []

        for punch in punch_times:

            if punch.tzinfo is None:
                local_punch = punch
            else:
                local_punch = (
                    punch.astimezone(timezone)
                    .replace(tzinfo=None)
                )

            local_punches.append(local_punch)

        local_punches.sort()

        # -------------------------------------------------------------
        # GROUP PUNCHES BY LOCAL CALENDAR DATE
        # -------------------------------------------------------------
        punches_by_date = defaultdict(list)

        for punch in local_punches:
            punches_by_date[punch.date()].append(punch)

        attendance_values = []
        mispunch_values = []

        # -------------------------------------------------------------
        # PROCESS EACH CALENDAR DAY INDEPENDENTLY
        # -------------------------------------------------------------
        for current_date in sorted(punches_by_date):

            current_punches = punches_by_date[current_date]

            if not current_punches:
                continue

            _logger.info(
                "📅 CALENDAR DAY PUNCH PROCESSING | "
                "Employee=%s | Date=%s | Punches=%s",
                employee.name,
                current_date,
                len(current_punches),
            )

            index = 0

            # ---------------------------------------------------------
            # PAIR SAME-DAY PUNCHES
            # ---------------------------------------------------------
            while index + 1 < len(current_punches):

                check_in_local = current_punches[index]
                check_out_local = current_punches[index + 1]

                if check_out_local > check_in_local:

                    attendance_values.append(
                        {
                            "employee_id": employee.id,
                            "check_in": self._convert_to_utc(
                                check_in_local
                            ),
                            "check_out": self._convert_to_utc(
                                check_out_local
                            ),
                            "shift_calendar_id": False,
                            "is_mispunch": False,
                            "mispunch_reason": False,
                            "in_mode": "technical",
                            "out_mode": "technical",
                        }
                    )

                    _logger.info(
                        "✅ SAME-DAY PAIR | Employee=%s | "
                        "Date=%s | IN=%s | OUT=%s",
                        employee.name,
                        current_date,
                        check_in_local,
                        check_out_local,
                    )

                    index += 2
                    continue

                # -----------------------------------------------------
                # INVALID ORDER - DEFENSIVE ONLY
                # -----------------------------------------------------
                _logger.warning(
                    "⚠️ INVALID BIOMETRIC PUNCH ORDER | "
                    "Employee=%s | Date=%s | Punch=%s",
                    employee.name,
                    current_date,
                    check_in_local,
                )

                index += 1

            # ---------------------------------------------------------
            # LAST UNMATCHED PUNCH
            # ---------------------------------------------------------
            if index < len(current_punches):

                check_in_local = current_punches[index]

                attendance_values.append(
                    {
                        "employee_id": employee.id,
                        "check_in": self._convert_to_utc(
                            check_in_local
                        ),
                        # IMPORTANT:
                        # Keep the attendance OPEN.
                        # Do NOT use check_in as check_out.
                        "check_out": False,
                        "shift_calendar_id": False,
                        "is_mispunch": False,
                        "mispunch_reason": False,
                        "in_mode": "technical",
                        "out_mode": "technical",
                    }
                )

                _logger.info(
                    "🟡 OPEN BIOMETRIC ATTENDANCE | "
                    "Employee=%s | Date=%s | IN=%s | "
                    "Waiting for checkout",
                    employee.name,
                    current_date,
                    check_in_local,
                )

        return attendance_values, mispunch_values, 0

    MAX_OPEN_HOURS = 20

    def _process_punches_sequentially(self, employee, punch_times):
        """
        Pair biometric punches one by one, oldest first.

        For every punch:
        - No open attendance            -> CHECK IN (stays open).
        - Open attendance, <= 20 hours  -> this punch is the CHECK OUT
                                           (works for night shifts too).
        - Open attendance, > 20 hours   -> forgotten checkout. The old
                                           attendance is closed with THIS
                                           punch (flagged mispunch) and the
                                           same punch becomes today's CHECK IN.
        Already processed punches are skipped, so re-processing is safe.
        """
        self.ensure_one()

        Attendance = self.env["hr.attendance"]
        timezone = self._get_attendance_schedule_timezone(employee)
        max_open = timedelta(hours=self.MAX_OPEN_HOURS)

        result = {
            "values": [],
            "mispunches": [],
            "created": Attendance,
            "updated": 0,
        }

        def to_utc(punch):
            # Aware datetimes (raw logs) are already exact moments: just
            # convert to UTC-naive. Naive ones (Excel import) are local time.
            if punch.tzinfo is not None:
                return punch.astimezone(pytz.UTC).replace(tzinfo=None)
            return self._convert_to_utc(punch)

        def as_values(att, check_out):
            return {
                "employee_id": employee.id,
                "check_in": att.check_in,
                "check_out": check_out,
                "shift_calendar_id": att.shift_calendar_id.id or False,
                "is_mispunch": att.is_mispunch,
                "mispunch_reason": att.mispunch_reason or False,
                "in_mode": "technical",
                "out_mode": "technical",
            }

        for punch_utc in sorted({to_utc(p) for p in punch_times}):

            # Already used as a check-in or check-out -> skip.
            if Attendance.search_count(
                [
                    ("employee_id", "=", employee.id),
                    "|",
                    ("check_in", "=", punch_utc),
                    ("check_out", "=", punch_utc),
                ]
            ):
                continue

            open_att = Attendance.search(
                [
                    ("employee_id", "=", employee.id),
                    ("check_out", "=", False),
                ],
                order="check_in desc, id desc",
                limit=1,
            )

            if open_att:

                if punch_utc <= open_att.check_in:
                    _logger.warning(
                        "PUNCH OLDER THAN OPEN CHECK-IN IGNORED | "
                        "Employee=%s | Punch=%s | Open IN=%s",
                        employee.name,
                        punch_utc,
                        open_att.check_in,
                    )
                    continue

                if punch_utc - open_att.check_in <= max_open:
                    # Normal checkout (also overnight shifts).
                    open_att.write(
                        {"check_out": punch_utc, "out_mode": "technical"}
                    )
                    result["updated"] += 1
                    result["values"].append(as_values(open_att, punch_utc))
                    continue

                # Forgotten checkout: close with this punch, flag mispunch,
                # then fall through so the same punch also checks in.
                reason = _(
                    "Checkout was missed for more than %s hours. "
                    "Closed by the next punch."
                ) % self.MAX_OPEN_HOURS
                open_att.write(
                    {
                        "check_out": punch_utc,
                        "is_mispunch": True,
                        "mispunch_reason": reason,
                        "out_mode": "technical",
                    }
                )
                result["updated"] += 1
                result["values"].append(as_values(open_att, punch_utc))
                result["mispunches"].append(
                    {
                        "employee_id": employee.id,
                        "shift_calendar_id": open_att.shift_calendar_id.id
                        or False,
                        "punch_datetime": open_att.check_in,
                        "punch_type": "missing_out",
                        "reason": reason,
                    }
                )

            new_att = Attendance.create(
                {
                    "employee_id": employee.id,
                    "check_in": punch_utc,
                    "shift_calendar_id": False,
                    "is_mispunch": False,
                    "mispunch_reason": False,
                    "in_mode": "technical",
                    "out_mode": "technical",
                }
            )
            result["created"] |= new_att
            result["values"].append(as_values(new_att, False))

        return result

    def _sync_mispunch_records(self, mispunch_values, attendance_values):
        """Create new mispunch records; resolve ones a re-import completed."""
        Mispunch = self.env["pharma.biometric.mispunch"]

        for vals in mispunch_values:
            attendance = self.env["hr.attendance"].search(
                [
                    ("employee_id", "=", vals["employee_id"]),
                    ("check_in", "=", vals["punch_datetime"]),
                ],
                limit=1,
            )
            existing = Mispunch.search(
                [
                    ("employee_id", "=", vals["employee_id"]),
                    ("punch_datetime", "=", vals["punch_datetime"]),
                    ("punch_type", "=", vals["punch_type"]),
                ],
                limit=1,
            )
            if existing:
                existing.write(
                    {"state": "detected", "attendance_id": attendance.id or False}
                )
            else:
                Mispunch.create(dict(vals, attendance_id=attendance.id or False))

        # A previously detected mispunch whose attendance now has a real
        # check-out (later import supplied it) is resolved.
        open_keys = {(v["employee_id"], v["punch_datetime"]) for v in mispunch_values}
        completed = [
            v
            for v in attendance_values
            if not v["is_mispunch"]
            and (v["employee_id"], v["check_in"]) not in open_keys
        ]
        for vals in completed:
            pending = Mispunch.search(
                [
                    ("employee_id", "=", vals["employee_id"]),
                    ("punch_datetime", "=", vals["check_in"]),
                    ("state", "=", "detected"),
                ]
            )
            if pending:
                pending.write({"state": "resolved"})

    # -------------------------------------------------------------------------
    # AUTOMATIC EXTRA SHIFT DETECTION
    # -------------------------------------------------------------------------

    def _get_shift_detection_tolerance_minutes(self):
        """
        Tolerance used while matching biometric attendance against a
        configured resource.calendar shift.

        Example:
            Configured Shift A = 06:00 - 14:30
            Imported attendance = 06:05 - 14:27

        This can still be recognised as Shift A.
        """
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "pharma.attendance.extra_shift_detection_tolerance_minutes",
                "15",
            )
        )

        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 15

    def _get_normal_employee_calendar(self, employee):
        """
        Return the employee's normal Working Hours calendar.

        Company Working Hours are used as fallback.
        """
        return employee.resource_calendar_id or employee.company_id.resource_calendar_id

    def _is_general_shift_calendar(self, calendar):
        """
        Return True when the calendar represents General Shift.

        General Shift employees may work overtime, so we must never
        automatically convert their overtime into an Extra Shift.
        """
        if not calendar:
            return False

        name = (calendar.name or "").strip().lower()

        return "general shift" in name or name == "general"

    def _get_shift_calendar_candidates(self, employee):
        """
        Return configured non-General shift calendars that can be
        automatically detected from biometric attendance.

        General Shift is deliberately excluded because overtime for a
        General Shift employee must remain overtime.
        """
        Calendar = self.env["resource.calendar"]

        calendars = Calendar.search(
            [
                ("company_id", "in", [False, employee.company_id.id]),
                ("active", "=", True),
            ]
        )

        normal_calendar = self._get_normal_employee_calendar(employee)

        return calendars.filtered(
            lambda calendar: calendar.id
            != (normal_calendar.id if normal_calendar else False)
            and not self._is_general_shift_calendar(calendar)
        )

    def _get_attendance_schedule_timezone(self, employee):
        """
        Return the timezone used for attendance schedule calculations.
        Priority:
            1. Employee Working Hours timezone
            2. Company Working Hours timezone
            3. Current user's timezone
            4. UTC
        """
        timezone_name = (
            employee.resource_calendar_id.tz
            or employee.company_id.resource_calendar_id.tz
            or self.env.user.tz
            or "UTC"
        )

        try:
            return pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "UNKNOWN TIMEZONE %s | Falling back to UTC",
                timezone_name,
            )
            return pytz.UTC

    def _get_calendar_expected_interval(
        self,
        calendar,
        check_date,
        employee,
    ):
        """
        Get the main working interval for a calendar on a particular date.

        The returned interval is in the employee's local timezone and is
        suitable for comparison with the biometric punch pair.

        Overnight shifts such as Shift C are supported.
        """
        if not calendar:
            return False

        timezone = self._get_attendance_schedule_timezone(employee)

        local_start = timezone.localize(
            datetime.combine(
                check_date,
                datetime.min.time(),
            )
        )

        # Look two days ahead so overnight Shift C can be captured.
        local_end = timezone.localize(
            datetime.combine(
                check_date + timedelta(days=2),
                datetime.min.time(),
            )
        )

        resource = employee.resource_id

        if resource:
            result = calendar._attendance_intervals_batch(
                local_start,
                local_end,
                resources=resource,
                tz=timezone,
            )
            intervals = result.get(resource.id, [])
        else:
            result = calendar._attendance_intervals_batch(
                local_start,
                local_end,
                tz=timezone,
            )
            intervals = result.get(False, [])

        if not intervals:
            return False

        usable_intervals = []

        for interval in intervals:
            if not isinstance(interval, (tuple, list)):
                continue

            if len(interval) < 2:
                continue

            start = interval[0]
            end = interval[1]

            if not start or not end or end <= start:
                continue

            # Normalize to the employee's local timezone.
            if start.tzinfo is None:
                start = timezone.localize(start)

            if end.tzinfo is None:
                end = timezone.localize(end)

            start_local = start.astimezone(timezone).replace(tzinfo=None)

            end_local = end.astimezone(timezone).replace(tzinfo=None)

            # The shift belongs to the date on which it starts.
            if start_local.date() != check_date:
                continue

            usable_intervals.append((start_local, end_local))

        if not usable_intervals:
            return False

        usable_intervals.sort(key=lambda item: item[0])

        # A normal shift should have one continuous main interval.
        # If Odoo splits the same shift into pieces, use the first start
        # and final end.
        return (
            usable_intervals[0][0],
            usable_intervals[-1][1],
        )

    def _attendance_matches_calendar(
        self,
        check_in_local,
        check_out_local,
        calendar,
        employee,
    ):
        """
        Check whether an imported attendance pair matches a configured
        resource.calendar shift.

        Matching is based on both start and end time, not merely on the
        amount of worked time.
        """
        if not check_in_local or not check_out_local:
            return False

        check_date = check_in_local.date()

        expected = self._get_calendar_expected_interval(
            calendar,
            check_date,
            employee,
        )

        if not expected:
            return False

        expected_start, expected_end = expected

        tolerance = timedelta(minutes=self._get_shift_detection_tolerance_minutes())

        start_difference = abs(check_in_local - expected_start)

        end_difference = abs(check_out_local - expected_end)

        return start_difference <= tolerance and end_difference <= tolerance

    def _get_attendance_schedule_timezone(self, employee):
        """
        Return the timezone used for attendance schedule calculations.
        """
        timezone_name = (
            employee.resource_calendar_id.tz
            or employee.company_id.resource_calendar_id.tz
            or self.env.user.tz
            or "UTC"
        )

        try:
            return pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            _logger.warning(
                "UNKNOWN TIMEZONE %s | Falling back to UTC",
                timezone_name,
            )
            return pytz.UTC

    def _detect_imported_extra_shifts(
        self,
        employee,
        attendance_values,
    ):
        """
        Detect genuine Extra Shifts from imported biometric attendance.

        Rules:
        - Manual Extra Shift assignments remain untouched.
        - General Shift overtime is NOT converted into Extra Shift.
        - The employee must first have worked their normal shift on that date.
        - A second attendance pair must match a configured non-General shift.
        - The normal calendar itself is never created as an Extra Shift.
        """

        if not employee or not attendance_values:
            return []

        normal_calendar = self._get_normal_employee_calendar(employee)

        if not normal_calendar:
            return []

        # General Shift employees can work overtime.
        # Their overtime must NOT become an Extra Shift.
        if self._is_general_shift_calendar(normal_calendar):
            _logger.info(
                "AUTO EXTRA SHIFT SKIPPED | Employee=%s | "
                "Reason=General Shift employee",
                employee.name,
            )
            return []

        candidates = self._get_shift_calendar_candidates(employee)

        if not candidates:
            return []

        timezone = self._get_attendance_schedule_timezone(employee)

        imported_pairs = []

        for values in attendance_values:

            if values.get("employee_id") != employee.id:
                continue

            check_in_utc = values.get("check_in")
            check_out_utc = values.get("check_out")

            if not check_in_utc or not check_out_utc:
                continue

            if check_out_utc <= check_in_utc:
                continue

            check_in_local = (
                pytz.UTC.localize(check_in_utc)
                .astimezone(timezone)
                .replace(tzinfo=None)
            )

            check_out_local = (
                pytz.UTC.localize(check_out_utc)
                .astimezone(timezone)
                .replace(tzinfo=None)
            )

            imported_pairs.append(
                {
                    "values": values,
                    "check_in": check_in_local,
                    "check_out": check_out_local,
                }
            )

        if len(imported_pairs) < 2:
            return []

        imported_pairs.sort(key=lambda item: item["check_in"])

        # -------------------------------------------------------------
        # GROUP ATTENDANCE PAIRS BY THE DATE OF THEIR CHECK-IN
        # -------------------------------------------------------------

        pairs_by_date = defaultdict(list)

        for pair in imported_pairs:
            pairs_by_date[pair["check_in"].date()].append(pair)

        detected = []

        # -------------------------------------------------------------
        # PROCESS EACH DAY
        # -------------------------------------------------------------

        for check_date, day_pairs in pairs_by_date.items():

            # ---------------------------------------------------------
            # FIRST: CONFIRM THAT THE NORMAL SHIFT WAS WORKED
            # ---------------------------------------------------------

            normal_shift_worked = False

            for pair in day_pairs:

                if self._attendance_matches_calendar(
                    pair["check_in"],
                    pair["check_out"],
                    normal_calendar,
                    employee,
                ):
                    normal_shift_worked = True
                    break

            # If the employee did not work the normal shift,
            # do NOT interpret another shift as an Extra Shift.
            if not normal_shift_worked:
                _logger.info(
                    "AUTO EXTRA SHIFT SKIPPED | Employee=%s | Date=%s | "
                    "Reason=Normal shift not detected",
                    employee.name,
                    check_date,
                )
                continue

            # ---------------------------------------------------------
            # SECOND: LOOK FOR AN ADDITIONAL SHIFT
            # ---------------------------------------------------------

            for pair in day_pairs:

                # This pair is the normal shift.
                if self._attendance_matches_calendar(
                    pair["check_in"],
                    pair["check_out"],
                    normal_calendar,
                    employee,
                ):
                    continue

                matched_calendar = False

                for calendar in candidates:

                    if self._attendance_matches_calendar(
                        pair["check_in"],
                        pair["check_out"],
                        calendar,
                        employee,
                    ):
                        matched_calendar = calendar
                        break

                if not matched_calendar:
                    continue

                detected.append(
                    {
                        "employee": employee,
                        "date": check_date,
                        "calendar": matched_calendar,
                        "check_in": pair["check_in"],
                        "check_out": pair["check_out"],
                    }
                )

                _logger.info(
                    "AUTO EXTRA SHIFT DETECTED | Employee=%s | Date=%s | "
                    "Shift=%s | IN=%s | OUT=%s",
                    employee.name,
                    check_date,
                    matched_calendar.name,
                    pair["check_in"],
                    pair["check_out"],
                )

        return detected

    def _create_imported_extra_shifts(
        self,
        employee,
        attendance_values,
    ):
        """
        Create automatically detected Extra Shifts directly in Odoo Planning.

        Working Hours remains the employee's primary shift.
        Automatically detected additional shifts are created as
        published Planning slots.

        Re-importing the same biometric data does not create duplicates.
        """

        detected = self._detect_imported_extra_shifts(
            employee,
            attendance_values,
        )

        if not detected:
            return self.env["planning.slot"]

        PlanningSlot = self.env["planning.slot"]
        PlanningTemplate = self.env["planning.slot.template"]

        created_slots = PlanningSlot

        for item in detected:
            check_date = item["date"]
            calendar = item["calendar"]
            check_in = item["check_in"]
            check_out = item["check_out"]

            if not employee.resource_id:
                continue

            shift_name = (calendar.name or "").strip()

            if not shift_name:
                continue

            # ---------------------------------------------------------
            # FIND EXISTING PLANNING SLOT
            # ---------------------------------------------------------
            existing_slot = PlanningSlot.search(
                [
                    ("resource_id", "=", employee.resource_id.id),
                    ("start_datetime", "=", check_in),
                    ("end_datetime", "=", check_out),
                ],
                limit=1,
            )

            if existing_slot:
                created_slots |= existing_slot
                continue

            # ---------------------------------------------------------
            # FIND THE PLANNING TEMPLATE FOR THIS SHIFT
            #
            # shift_assigned on planning.slot is related to
            # template_id.shift_assigned, so we must assign the template.
            # ---------------------------------------------------------
            template = PlanningTemplate.search(
                [
                    ("shift_assigned", "=ilike", shift_name),
                ],
                limit=1,
            )

            values = {
                "resource_id": employee.resource_id.id,
                "start_datetime": check_in,
                "end_datetime": check_out,
                "state": "published",
            }

            if template:
                values["template_id"] = template.id
            else:
                # Fallback: the attendance engine can use slot.name
                # when shift_assigned/template is not available.
                values["name"] = shift_name

            slot = PlanningSlot.create(values)

            created_slots |= slot

            _logger.info(
                "AUTO EXTRA SHIFT CREATED IN PLANNING | "
                "Employee=%s | Date=%s | Shift=%s | IN=%s | OUT=%s | Slot=%s",
                employee.name,
                check_date,
                shift_name,
                check_in,
                check_out,
                slot.id,
            )

        return created_slots

    # def _create_attendances(self, punches):
    #     """
    #     Create/update hr.attendance records from biometric punches.
    #     BIOMETRIC RULE
    #     --------------
    #     For each employee, all punches are sorted chronologically and numbered
    #     continuously across dates:
    #         1st punch  -> CHECK IN
    #         2nd punch  -> CHECK OUT
    #         3rd punch  -> CHECK IN
    #         4th punch  -> CHECK OUT
    #         ...
    #     The odd/even sequence NEVER resets when the date changes.
    #     Re-import behaviour:
    #         Existing attendance is matched by employee + exact check-in.
    #         If the same punch is imported again, the existing attendance is
    #         updated instead of creating a duplicate.
    #     """
    #     self.ensure_one()
    #     _logger.info(
    #         "STARTING ODD-EVEN BIOMETRIC ATTENDANCE CREATION | "
    #         "Import ID=%s | Punches=%s",
    #         self.id,
    #         len(punches),
    #     )
    #     # -------------------------------------------------------------
    #     # GROUP PUNCHES BY EMPLOYEE
    #     # ------------------------------------------------------------
    #     employee_punches = defaultdict(list)
    #     for punch in punches:
    #         employee_punches[punch["enno"]].append(punch["datetime"])
    #     # -------------------------------------------------------------
    #     # SORT EMPLOYEE PUNCHES
    #     # -------------------------------------------------------------
    #     # This is critical: odd/even occurrence is assigned only after all
    #     # punches for the employee have been sorted chronologically.
    #     for enno in employee_punches:
    #         employee_punches[enno].sort()
    #         _logger.info(
    #             "EMPLOYEE PUNCH SEQUENCE | EnNo=%s | Total Punches=%s",
    #             enno,
    #             len(employee_punches[enno]),
    #         )
    #         for occurrence, punch_datetime in enumerate(
    #             employee_punches[enno],
    #             start=1,
    #         ):
    #             punch_type = "CHECK IN" if occurrence % 2 == 1 else "CHECK OUT"
    #             _logger.debug(
    #                 "PUNCH OCCURRENCE | EnNo=%s | Occurrence=%s | "
    #                 "Type=%s | DateTime=%s",
    #                 enno,
    #                 occurrence,
    #                 punch_type,
    #                 punch_datetime,
    #             )
    #     # -------------------------------------------------------------
    #     # FIND ODOO EMPLOYEES
    #     # -------------------------------------------------------------
    #     employees = self.env["hr.employee"].search(
    #         [
    #             ("barcode", "in", list(employee_punches.keys())),
    #         ]
    #     )
    #     employee_by_badge_id = {
    #         self._normalize_employee_number(employee.barcode): employee
    #         for employee in employees
    #         if employee.barcode
    #     }
    #     attendance_values = []
    #     mispunch_values = []
    #     unmatched_employees = 0
    #     unmatched_punches = 0
    #     # -------------------------------------------------------------
    #     # BUILD ATTENDANCE VALUES EMPLOYEE-WISE
    #     # -------------------------------------------------------------
    #     for enno, punch_times in employee_punches.items():
    #         employee = employee_by_badge_id.get(enno)
    #         if not employee:
    #             unmatched_employees += 1
    #             unmatched_punches += len(punch_times)
    #             _logger.warning(
    #                 "UNMATCHED EMPLOYEE | EnNo=%s | Punches=%s",
    #                 enno,
    #                 len(punch_times),
    #             )
    #             continue
    #         values, employee_mispunches, employee_unmatched = (
    #             self._prepare_shift_attendance_values(
    #                 employee,
    #                 punch_times,
    #             )
    #         )
    #         attendance_values.extend(values)
    #         mispunch_values.extend(employee_mispunches)
    #         unmatched_punches += employee_unmatched

    #         # -------------------------------------------------------------
    #         # AUTOMATIC EXTRA SHIFT → PLANNING
    #         # -------------------------------------------------------------
    #         self._create_imported_extra_shifts(
    #             employee,
    #             values,
    #         )

    #         # -------------------------------------------------------------
    #         # -------------------------------------------------------------
    #         # SHIFT SOURCE
    #         # -------------------------------------------------------------
    #         #
    #         # Shift assignment is now handled exclusively by Odoo Planning.
    #         # Do NOT detect or create employee.extra.shift records from
    #         # biometric punches.
    #         #
    #         # The biometric odd/even pairing above remains unchanged.
    #         # -------------------------------------------------------------

    #     # -------------------------------------------------------------
    #     # NO MATCHED EMPLOYEE / NO ATTENDANCE VALUES
    #     # -------------------------------------------------------------
    #     if not attendance_values:
    #         self.write(
    #             {
    #                 "state": "processed",
    #                 "total_records": len(punches),
    #                 "attendance_created": 0,
    #                 "unmatched_employees": unmatched_employees,
    #                 "unmatched_punches": unmatched_punches,
    #             }
    #         )
    #         _logger.warning(
    #             "NO ATTENDANCE VALUES CREATED | Import ID=%s | "
    #             "Unmatched Employees=%s | Unmatched Punches=%s",
    #             self.id,
    #             unmatched_employees,
    #             unmatched_punches,
    #         )
    #         return
    #     # -------------------------------------------------------------
    #     # LOAD EXISTING ATTENDANCES FOR SAFE RE-IMPORT
    #     # -------------------------------------------------------------
    #     employee_ids = list({values["employee_id"] for values in attendance_values})
    #     min_check_in = min(values["check_in"] for values in attendance_values)
    #     max_check_in = max(values["check_in"] for values in attendance_values)
    #     existing_attendances = self.env["hr.attendance"].search(
    #         [
    #             ("employee_id", "in", employee_ids),
    #             ("check_in", ">=", min_check_in),
    #             ("check_in", "<=", max_check_in),
    #         ],
    #         order="employee_id, check_in, id",
    #     )
    #     # Match only by employee + exact check-in.
    #     # Shift schedule is deliberately NOT used to determine IN/OUT.
    #     existing_candidates = defaultdict(list)
    #     for attendance in existing_attendances:
    #         if not attendance.check_in:
    #             continue
    #         key = (
    #             attendance.employee_id.id,
    #             attendance.check_in.replace(microsecond=0),
    #         )
    #         existing_candidates[key].append(attendance)
    #     matched_ids = set()
    #     records_to_update = []
    #     records_to_create = []

    #     # -------------------------------------------------------------
    #     # UPDATE EXISTING OR CREATE NEW ATTENDANCE
    #     # -------------------------------------------------------------

    #     for values in attendance_values:
    #         check_in = values["check_in"]
    #         key = (
    #             values["employee_id"],
    #             check_in.replace(microsecond=0),
    #         )
    #         candidate = next(
    #             (
    #                 attendance
    #                 for attendance in existing_candidates.get(key, [])
    #                 if attendance.id not in matched_ids
    #             ),
    #             None,
    #         )
    #         if candidate:
    #             matched_ids.add(candidate.id)
    #             records_to_update.append(
    #                 (
    #                     candidate,
    #                     {
    #                         "check_in": values["check_in"],
    #                         "check_out": values["check_out"],
    #                         "shift_calendar_id": values["shift_calendar_id"],
    #                         "is_mispunch": values["is_mispunch"],
    #                         "mispunch_reason": values["mispunch_reason"],
    #                         "in_mode": values.get("in_mode", "technical"),
    #                         "out_mode": values.get("out_mode", "technical"),
    #                     },
    #                 )
    #             )
    #             _logger.info(
    #                 "ATTENDANCE UPDATED | Employee=%s | "
    #                 "Check In=%s | Check Out=%s | Mispunch=%s",
    #                 candidate.employee_id.name,
    #                 values["check_in"],
    #                 values["check_out"],
    #                 values["is_mispunch"],
    #             )
    #         else:
    #             records_to_create.append(values)
    #             _logger.info(
    #                 "ATTENDANCE TO CREATE | Employee ID=%s | "
    #                 "Check In=%s | Check Out=%s | Mispunch=%s",
    #                 values["employee_id"],
    #                 values["check_in"],
    #                 values["check_out"],
    #                 values["is_mispunch"],
    #             )
    #     # -------------------------------------------------------------
    #     # WRITE UPDATES
    #     # -------------------------------------------------------------
    #     for attendance, values in records_to_update:
    #         attendance.write(values)
    #     # -------------------------------------------------------------
    #     # CREATE NEW ATTENDANCES
    #     # -------------------------------------------------------------
    #     created_attendances = self.env["hr.attendance"]
    #     if records_to_create:
    #         created_attendances = self.env["hr.attendance"].create(records_to_create)
    #     processed_count = len(records_to_update) + len(created_attendances)
    #     # -------------------------------------------------------------
    #     # SAVE / RESOLVE MIS-PUNCH RECORDS
    #     # -------------------------------------------------------------
    #     self._sync_mispunch_records(mispunch_values, attendance_values)
    #     # -------------------------------------------------------------
    #     # STORE MIS-PUNCHES
    #     # -------------------------------------------------------------
    #     # A later import containing the missing checkout can resolve an
    #     # earlier detected mispunch.
    #     # -------------------------------------------------------------
    #     # FINISH IMPORT
    #     # -------------------------------------------------------------
    #     _logger.info(
    #         "ODD-EVEN BIOMETRIC ATTENDANCE PROCESSING COMPLETE | "
    #         "Import ID=%s | Punches=%s | Attendances Processed=%s | "
    #         "Updated=%s | Created=%s | Unmatched Employees=%s | "
    #         "Unmatched Punches=%s | Mispunches=%s",
    #         self.id,
    #         len(punches),
    #         processed_count,
    #         len(records_to_update),
    #         len(created_attendances),
    #         unmatched_employees,
    #         unmatched_punches,
    #     )
    #     self.write(
    #         {
    #             "state": "processed",
    #             "total_records": len(punches),
    #             "attendance_created": processed_count,
    #             "unmatched_employees": unmatched_employees,
    #             "unmatched_punches": unmatched_punches,
    #         }
    #     )

    def _create_attendances(self, punches):
        """
        Create/update hr.attendance records from biometric punches.

        BIOMETRIC RULE
        --------------
        Attendance pairing is handled by _prepare_shift_attendance_values():

            1st punch -> CHECK IN
            2nd punch -> CHECK OUT
            3rd punch -> CHECK IN
            4th punch -> CHECK OUT
            ...

        Pairing is sequential with a 20-hour rule (see
        _process_punches_sequentially); it does NOT reset per day.

        Rules:
        - Same-day open attendance remains OPEN.
        - A later same-day punch closes the existing open attendance.
        - Different calendar days are never paired together.
        - Existing attendance is matched by employee + exact check-in.
        - Re-importing the same biometric data does not create duplicates.
        - Previous-day open biometric attendances are handled by
        hr.attendance.create().
        """

        self.ensure_one()

        _logger.info(
            "🚀 STARTING CALENDAR-DAY BIOMETRIC ATTENDANCE CREATION | "
            "Import ID=%s | Punches=%s",
            self.id,
            len(punches),
        )

        Attendance = self.env["hr.attendance"]

        # -------------------------------------------------------------
        # 1. GROUP PUNCHES BY EMPLOYEE
        # -------------------------------------------------------------
        employee_punches = defaultdict(list)

        for punch in punches:
            employee_punches[punch["enno"]].append(
                punch["datetime"]
            )

        # -------------------------------------------------------------
        # 2. SORT PUNCHES EMPLOYEE-WISE
        # -------------------------------------------------------------
        for enno in employee_punches:
            employee_punches[enno].sort()

            _logger.info(
                "👤 EMPLOYEE PUNCH SEQUENCE | "
                "EnNo=%s | Total Punches=%s",
                enno,
                len(employee_punches[enno]),
            )

        # -------------------------------------------------------------
        # 3. FIND ODOO EMPLOYEES
        # -------------------------------------------------------------
        employees = self.env["hr.employee"].search(
            [
                (
                    "barcode",
                    "in",
                    list(employee_punches.keys()),
                ),
            ]
        )

        employee_by_badge_id = {
            self._normalize_employee_number(employee.barcode): employee
            for employee in employees
            if employee.barcode
        }

        attendance_values = []
        mispunch_values = []

        unmatched_employees = 0
        unmatched_punches = 0

        # -------------------------------------------------------------
        # 4. SEQUENTIAL PAIRING (20-HOUR RULE) - EMPLOYEE-WISE
        # -------------------------------------------------------------
        created_attendances = Attendance
        updated_count = 0
        values_by_employee = defaultdict(list)
        employee_by_id = {}
        unmatched_enno = set()

        # FIFO: the oldest punch goes into Odoo first, across ALL
        # employees (stable sort keeps raw-log id order for equal times).
        for punch in sorted(punches, key=lambda p: p["datetime"]):

            enno = punch["enno"]
            employee = employee_by_badge_id.get(enno)

            if not employee:
                unmatched_enno.add(enno)
                unmatched_punches += 1
                continue

            result = self._process_punches_sequentially(
                employee,
                [punch["datetime"]],
            )

            attendance_values.extend(result["values"])
            mispunch_values.extend(result["mispunches"])
            created_attendances |= result["created"]
            updated_count += result["updated"]
            values_by_employee[employee.id].extend(result["values"])
            employee_by_id[employee.id] = employee

        unmatched_employees = len(unmatched_enno)

        # KEEP EXISTING EXTRA SHIFT / PLANNING LOGIC (once per employee)
        for employee_id, values in values_by_employee.items():
            self._create_imported_extra_shifts(
                employee_by_id[employee_id],
                values,
            )

        # -------------------------------------------------------------
        # 5. NOTHING TO PROCESS
        # -------------------------------------------------------------
        if not attendance_values:

            self.write(
                {
                    "state": "processed",
                    "total_records": len(punches),
                    "attendance_created": 0,
                    "unmatched_employees": unmatched_employees,
                    "unmatched_punches": unmatched_punches,
                }
            )

            _logger.warning(
                "⚠️ NO ATTENDANCE VALUES CREATED | "
                "Import ID=%s | "
                "Unmatched Employees=%s | "
                "Unmatched Punches=%s",
                self.id,
                unmatched_employees,
                unmatched_punches,
            )

            return

        # -------------------------------------------------------------
        # 7. SAVE / RESOLVE MIS-PUNCH RECORDS
        # -------------------------------------------------------------
        self._sync_mispunch_records(
            mispunch_values,
            attendance_values,
        )

        # -------------------------------------------------------------
        # 8. UPDATE IMPORT RECORD
        # -------------------------------------------------------------
        processed_count = (
            updated_count
            + len(created_attendances)
        )

        self.write(
            {
                "state": "processed",
                "total_records": len(punches),
                "attendance_created": len(
                    created_attendances
                ),
                "unmatched_employees": unmatched_employees,
                "unmatched_punches": unmatched_punches,
            }
        )

        _logger.info(
            "🏁 CALENDAR-DAY BIOMETRIC PROCESSING COMPLETE | "
            "Import ID=%s | Punches=%s | "
            "Processed=%s | Created=%s | Updated=%s | "
            "Unmatched Employees=%s | Unmatched Punches=%s",
            self.id,
            len(punches),
            processed_count,
            len(created_attendances),
            updated_count,
            unmatched_employees,
            unmatched_punches,
        )