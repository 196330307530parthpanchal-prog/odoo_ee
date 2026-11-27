{
    "name": "Biometric Attendance Process New",
    "version": "18.0.3.1.0",
    "category": "Human Resources/Attendances",
    "summary": "Import biometric attendance logs and generate attendance reports",
    "description": """
Biometric Attendance Process
============================

Imports biometric attendance logs from Excel and converts
employee punches into Odoo attendance records.

Processing rule:
- The No column is ignored.
- EnNo is mapped to the employee's Biometric Employee No.
- Punches are grouped employee-wise.
- Punches are sorted chronologically for each employee.
- Employee Working Hours and date-based Extra Shifts are the authoritative schedule source.
- The employee's normal Working Hours are always considered.
- Active Extra Shift assignments are added for their configured date range.
- Punches are processed chronologically against the employee's effective work intervals.
- Attendance always starts with a check-in.
- A later punch is used as the check-out only when it belongs to the same expected work interval.
- A missing check-out creates a zero-duration mispunch attendance plus a dedicated mispunch record.
- Punches are never paired across unrelated expected work intervals merely because they are consecutive in the file.

Attendance Report
=================

Generates a monthly attendance report in Excel format.

The report contains:
- Employee details
- Employee code
- Employee name
- Date of joining
- Branch
- Department
- Designation
- Daily In Time
- Daily Out Time
- Working Hours
- Attendance Status
""",
    "author": "Areterix Technologies LLP",
    "website": "",
    "license": "LGPL-3",

    "depends": [
        "hr",
        "hr_attendance",
        "hr_holidays",
        "pharma_planning_aretx",
    ],

    "external_dependencies": {
        "python": [
            "openpyxl",
            "xlsxwriter",
            "zk",
        ],
    },

    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",

        "views/biometric_device_views.xml",
        "views/biometric_attendance_log_views.xml",
        "wizard/import_attendance_wizard_views.xml",
        "views/biometric_attendance_views.xml",
        "views/hr_employee_views.xml",
        "views/attendance_report_views.xml",
        "views/attendance_finalize_wizard_views.xml",

        "data/cron.xml",
        "data/mispunch_email_template.xml",
        "data/mispunch_email_cron.xml",
        "data/absent_reminder_email_template.xml",
        "data/absent_reminder_cron.xml",
    ],

    "assets": {
        "web.assets_backend": [
            "pharma_bioattendance_aretx/static/src/js/attendance_report_button.js",
            "pharma_bioattendance_aretx/static/src/xml/attendance_report_button.xml",
            "pharma_bioattendance_aretx/static/src/css/attendance_report_button.css",
        ],
    },

    "installable": True,
    "application": True,
}