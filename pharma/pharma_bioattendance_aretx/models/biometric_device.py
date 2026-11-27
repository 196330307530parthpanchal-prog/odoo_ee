import logging
from datetime import datetime, date, time as dtime
from collections import defaultdict
import pytz
from odoo import models, fields, api, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class BiometricDevice(models.Model):
    _name = 'biometric.device'
    _description = 'Biometric Device'
    _order = 'name'

    name = fields.Char(string='Device Name', required=True)
    ip_address = fields.Char(string='IP Address', required=True)
    port = fields.Integer(string='Port', default=4370)
    password = fields.Integer(string='Password', default=0)
    timezone = fields.Selection(
        selection=lambda self: [(tz, tz) for tz in pytz.all_timezones],
        string='Device Timezone',
        default='Asia/Kolkata',
        required=True,
    )
    active = fields.Boolean(string='Active', default=True)
    last_sync = fields.Datetime(string='Last Sync', readonly=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    def _localize_to_utc(self, naive_dt):
        self.ensure_one()
        device_tz = pytz.timezone(self.timezone or 'UTC')
        localized = device_tz.localize(naive_dt, is_dst=None)
        return localized.astimezone(pytz.utc).replace(tzinfo=None)

    # ----------------------------------------------------------
    # PRIVATE: Connect / Disconnect helpers
    # ----------------------------------------------------------

    def _get_zk_connection(self):
        """Return a connected ZK instance or raise UserError."""
        try:
            from zk import ZK
        except ImportError:
            raise UserError(_(
                "Python library 'pyzk' is not installed.\n"
                "Run:  pip install pyzk"
            ))

        self.ensure_one()
        _logger.info(
            "Connecting to device '%s' at %s:%s",
            self.name, self.ip_address, self.port,
        )
        zk=0
        if self.password !=0 :
            print("with password")
            zk = ZK(
                self.ip_address,
                port=self.port,
                timeout=10,
                password=self.password,
            )
        else:
            print("without password")
            zk = ZK(
                self.ip_address,
                port=self.port,
                timeout=10,
                # password=self.password,
            )
        try:
            conn = zk.connect()
            _logger.info("Device '%s' connected successfully.", self.name)
            return conn
        except Exception as exc:
            _logger.error(
                "Failed to connect to device '%s': %s", self.name, exc
            )
            raise UserError(_(
                "Cannot connect to device '%(name)s' (%(ip)s:%(port)s).\n"
                "Error: %(err)s",
                name=self.name,
                ip=self.ip_address,
                port=self.port,
                err=str(exc),
            ))

    # ----------------------------------------------------------
    # BUTTON: Test Connection
    # ----------------------------------------------------------

    def action_test_connection(self):
        self.ensure_one()
        try:
            conn = self._get_zk_connection()
            fw = None
            try:
                fw = conn.get_firmware_version()
            except Exception:
                pass
            conn.disconnect()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _(
                        "Device '%(name)s' is reachable.%(fw)s",
                        name=self.name,
                        fw=f"  Firmware: {fw}" if fw else "",
                    ),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except UserError as exc:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': str(exc),
                    'type': 'danger',
                    'sticky': True,
                },
            }

    # ----------------------------------------------------------
    # BUTTON: Import Today Attendance
    # ----------------------------------------------------------

    def action_import_today(self):
        self.ensure_one()
        return self._import_attendance_for_date(date.today())

    # ----------------------------------------------------------
    # BUTTON: Import Selected Date (opens wizard)
    # ----------------------------------------------------------

    def action_open_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Attendance'),
            'res_model': 'import.attendance.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_device_id': self.id},
        }

    # ----------------------------------------------------------
    # BUTTON: Generate HR Attendance
    # ----------------------------------------------------------

    def action_generate_hr_attendance(self):
        self.ensure_one()
        self._generate_hr_attendance(device=self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('HR Attendance Generated'),
                'message': _('HR Attendance records have been created/updated.'),
                'type': 'success',
                'sticky': False,
            },
        }

    # ----------------------------------------------------------
    # CORE: Import attendance for a specific date
    # ----------------------------------------------------------

    def _import_attendance_for_date(self, target_date):
        """
        Connect to device, fetch logs for target_date,
        store into biometric.attendance.log, skip duplicates.
        """
        self.ensure_one()
        conn = self._get_zk_connection()

        try:
            # Device info
            try:
                _logger.info("Device time: %s", conn.get_time())
            except Exception:
                pass

            # Users
            users = conn.get_users()
            user_map = {str(u.user_id): u.name for u in users}
            _logger.info(
                "Device '%s' – total users: %d", self.name, len(users)
            )

            # Attendance logs
            logs = conn.get_attendance()
            _logger.info(
                "Device '%s' – total logs in device: %d",
                self.name, len(logs),
            )

            # Filter for target date
            day_logs = [
                att for att in logs
                if att.timestamp.date() == target_date
            ]
            _logger.info(
                "Device '%s' – logs for %s: %d",
                self.name, target_date, len(day_logs),
            )

            AttLog = self.env['biometric.attendance.log']
            imported = 0
            skipped = 0

            for att in day_logs:
                uid = str(att.user_id)
                emp_name = user_map.get(uid, 'Unknown')

                # Find mapped employee
                employee = self.env['hr.employee'].search(
                    [('barcode', '=', uid)], limit=1
                )
                if not employee:
                    _logger.warning(
                        "No employee mapping for biometric_user_id '%s' (%s)",
                        uid, emp_name,
                    )
                punch_utc = self._localize_to_utc(att.timestamp)

                # Check duplicate
                existing = AttLog.search([
                    ('biometric_user_id', '=', uid),
                    ('punch_time', '=', punch_utc),

                    # ('punch_time', '=', att.timestamp),
                ], limit=1)


                if existing:
                    skipped += 1
                    continue

                AttLog.create({
                    'employee_id': employee.id if employee else False,
                    'employee_name': emp_name,
                    'biometric_user_id': uid,
                    'attendance_date': target_date,
                    'punch_time': punch_utc,

                    'device_id': self.id,
                    'state': 'imported',
                })
                imported += 1
                # After import loop — build daily summary
                self._build_daily_summary(
                    target_date, user_map, day_logs
                )

            _logger.info(
                "Device '%s' – imported: %d, skipped (duplicate): %d",
                self.name, imported, skipped,
            )
            # After import loop — build daily summary
            self._build_daily_summary(
                target_date, user_map, day_logs
            )
        finally:
            conn.disconnect()
            _logger.info("Device '%s' disconnected.", self.name)

        self.write({'last_sync': fields.Datetime.now()})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Complete'),
                'message': _(
                    "Date: %(d)s  |  Imported: %(i)d  |  Skipped: %(s)d",
                    d=str(target_date), i=imported, s=skipped,
                ),
                'type': 'success',
                'sticky': False,
            },
        }

    # ----------------------------------------------------------
    # CORE: Generate HR Attendance
    # ----------------------------------------------------------

    @api.model
    def _generate_hr_attendance(self, device=None):
        """
        Generate HR attendance using the SAME processing path as
        biometric.attendance.log.

        IMPORTANT:
        Do not create hr.attendance records directly here.

        The architecture is:

            Biometric Device
                    ↓
            biometric.attendance.log
                    ↓
            action_process_attendance()
                    ↓
            pharma.biometric.attendance._create_attendances()
                    ↓
            hr.attendance

        This guarantees that live-device attendance uses the same
        day-wise / shift-wise / overnight / mispunch logic as the
        existing biometric attendance processing.
        """

        Log = self.env["biometric.attendance.log"]

        # ----------------------------------------------------------
        # Only process imported logs
        # ----------------------------------------------------------

        domain = [
            ("state", "=", "imported"),
        ]

        if device:
            domain.append(("device_id", "=", device.id))

        imported_logs = Log.search(
            domain,
            order="punch_time asc, id asc",
        )

        if not imported_logs:
            _logger.info(
                "BIOMETRIC DEVICE ATTENDANCE | "
                "No Imported logs found | Device=%s",
                device.name if device else "ALL",
            )
            return True

        _logger.info(
            "BIOMETRIC DEVICE ATTENDANCE | "
            "Processing %s Imported logs | Device=%s",
            len(imported_logs),
            device.name if device else "ALL",
        )

        # ----------------------------------------------------------
        # IMPORTANT:
        # Use the existing attendance-log processing method.
        #
        # This internally calls:
        #
        # biometric.attendance.log
        #        ↓
        # pharma.biometric.attendance._create_attendances()
        #
        # Therefore NO separate hr.attendance creation happens here.
        # ----------------------------------------------------------

        imported_logs.action_process_attendance()

        _logger.info(
            "BIOMETRIC DEVICE ATTENDANCE | "
            "Processing completed | Device=%s",
            device.name if device else "ALL",
        )

        return True

    # ----------------------------------------------------------
    # CRON: Hourly import for all active devices
    # ----------------------------------------------------------
    @api.model
    def cron_import_today_all_devices(self):
        """
        Cron:

        1. Fetch today's attendance from all active biometric devices.
        2. Process ALL attendance logs in Imported state.

        The processing step is independent of the device import so
        manually imported Excel records are also processed.
        """

        devices = self.search([('active', '=', True)])

        _logger.info(
            "CRON STARTED | Active devices: %s",
            len(devices),
        )

        # ==========================================================
        # STEP 1: FETCH FROM LIVE BIOMETRIC DEVICES
        # ==========================================================

        for device in devices:
            try:
                with self.env.cr.savepoint():
                    _logger.info(
                        "CRON DEVICE IMPORT START | Device: %s | ID: %s",
                        device.name,
                        device.id,
                    )

                    device._import_attendance_for_date(date.today())

                    _logger.info(
                        "CRON DEVICE IMPORT COMPLETED | Device: %s",
                        device.name,
                    )

            except Exception as exc:
                # The savepoint automatically rolls back the failed
                # device transaction to the savepoint.
                # Other devices and imported logs can still be processed.
                _logger.exception(
                    "CRON DEVICE IMPORT FAILED | Device: %s | Error: %s",
                    device.name,
                    exc,
                )

        # ==========================================================
        # STEP 2: PROCESS IMPORTED LOGS - STRICT FIFO (id ASC)
        # Same method as the manual Process button.
        # ==========================================================
        try:
            self.env['biometric.attendance.log']._process_imported_logs_fifo()
        except Exception as exc:
            _logger.exception(
                "CRON FIFO PROCESSING FAILED | Error: %s", exc
            )

        # ==========================================================
        # STEP 3: OPEN > 20 HOURS WITHOUT CHECKOUT = MISPUNCH
        # ==========================================================
        try:
            with self.env.cr.savepoint():
                self.env['pharma.biometric.attendance']._flag_overdue_open_attendances()
        except Exception as exc:
            _logger.exception(
                "CRON OVERDUE MISPUNCH CHECK FAILED | Error: %s", exc
            )

        return True

        # ----------------------------------------------------------
        # OLD batch processing (disabled - replaced by FIFO above)
        # ----------------------------------------------------------
        # # ==========================================================
        # # STEP 2: PROCESS ALL IMPORTED LOGS
        # # ==========================================================

        # try:
        #     imported_logs = self.env['biometric.attendance.log'].search(
        #         [('state', '=', 'imported')],
        #         order='punch_time asc, id asc',
        #     )

        #     _logger.info(
        #         "CRON PROCESSING | Imported attendance logs found: %s",
        #         len(imported_logs),
        #     )

        # except Exception as exc:
        #     _logger.exception(
        #         "CRON IMPORTED LOG SEARCH FAILED | Error: %s",
        #         exc,
        #     )
        #     return True

        # if not imported_logs:
        #     _logger.info(
        #         "CRON FINISHED | No Imported attendance logs found."
        #     )
        #     return True

        # try:
        #     with self.env.cr.savepoint():
        #         _logger.info(
        #             "CRON PROCESSING START | Processing %s Imported logs.",
        #             len(imported_logs),
        #         )

        #         imported_logs.action_process_attendance()

        #         _logger.info(
        #             "CRON PROCESSING COMPLETED | Processed logs: %s",
        #             len(imported_logs),
        #         )

        # except Exception as exc:
        #     # The savepoint automatically rolls back the processing
        #     # operation if a database error or other exception occurs.
        #     _logger.exception(
        #         "CRON PROCESSING FAILED | Error: %s",
        #         exc,
        #     )

        # return True

    def _build_daily_summary(self, target_date, user_map, day_logs):
        """
        Group all punches by user for target_date and
        create/update biometric.attendance.summary records.
        """
        from collections import defaultdict
        from datetime import time as dtime

        OFFICE_START = dtime(9, 0, 0)
        Summary = self.env['biometric.attendance.summary']

        grouped = defaultdict(list)
        for att in day_logs:
            grouped[str(att.user_id)].append(att.timestamp)

        for uid, punches in grouped.items():
            punches.sort()

            first_in = punches[0]
            last_out = punches[-1]
            total = len(punches)

            # Working hours as float (e.g. 8.5 = 8h 30m)
            if total > 1:
                delta = last_out - first_in
                wh = delta.total_seconds() / 3600.0
            else:
                wh = 0.0

            late = first_in.time() > OFFICE_START

            # Convert to UTC for storage
            first_in_utc = self._localize_to_utc(first_in)
            last_out_utc = self._localize_to_utc(last_out)

            # Punch history text
            history_lines = [
                f"{i}. {self._localize_to_utc(p)}"
                for i, p in enumerate(punches, 1)
            ]
            history = "\n".join(history_lines)

            # Employee mapping
            employee = self.env['hr.employee'].search(
                [('barcode', '=', uid)], limit=1
            )

            vals = {
                'employee_id': employee.id if employee else False,
                'employee_name': user_map.get(uid, 'Unknown'),
                'biometric_user_id': uid,
                'attendance_date': target_date,
                'device_id': self.id,
                'check_in': first_in_utc,
                'check_out': last_out_utc,
                'total_punches': total,
                'working_hours': wh,
                'late': late,
                'punch_history': history,
            }

            # Update if exists, else create
            existing = Summary.search([
                ('biometric_user_id', '=', uid),
                ('attendance_date', '=', target_date),
                ('device_id', '=', self.id),
            ], limit=1)

            if existing:
                existing.write(vals)
            else:
                Summary.create(vals)