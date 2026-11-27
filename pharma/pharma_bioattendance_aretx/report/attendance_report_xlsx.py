from datetime import timedelta

import xlsxwriter

from odoo import fields, models

from ..lib.xlsx_layout import write_attendance_sheet


class PharmaAttendanceReportXlsx(models.AbstractModel):
    _name = 'report.pharma.attendance.xlsx'
    _description = 'Pharma Attendance XLSX Report'

    # =====================================================================
    # ENTRY POINTS
    # =====================================================================
    def _get_report_values(self, docids, data=None):
        wizard = self.env['pharma.attendance.report.wizard'].browse(docids)
        return {
            'doc_ids': wizard.ids,
            'doc_model': 'pharma.attendance.report.wizard',
            'docs': wizard,
        }

    def _create_workbook(self, output, wizard):
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._generate_report(workbook, wizard)
        return workbook

    # =====================================================================
    # REPORT
    # =====================================================================
    def _generate_report(self, workbook, wizard):
        if wizard.start_date > wizard.end_date:
            raise ValueError('Start Date cannot be later than End Date.')

        first_day, last_day = wizard.start_date, wizard.end_date
        date_range = [first_day + timedelta(days=i)
                      for i in range((last_day - first_day).days + 1)]

        employees = self.env['hr.employee'].search(
            [], order='barcode asc, name asc')

        # One bulk calculation for everybody (no per-cell queries).
        results = self.env['pharma.attendance.engine'].compute_period(
            employees, first_day, last_day)

        rows = [{
            'code': self._get_employee_code(employee),
            'name': employee.name or '',
            'doj': self._get_employee_doj(employee),
            'branch': self._get_employee_branch(employee),
            'department': employee.department_id.name or '',
            'designation': employee.job_id.name or '',
            'days': results.get(employee.id, {}),
        } for employee in employees]

        write_attendance_sheet(
            workbook, rows, date_range,
            today=fields.Date.context_today(self))

    # =====================================================================
    # EMPLOYEE INFORMATION
    # =====================================================================
    def _get_employee_code(self, employee):
        """Badge ID (hr.employee.barcode) = biometric employee number."""
        return (employee.barcode or '') if 'barcode' in employee._fields else ''

    def _get_employee_doj(self, employee):
        """Date of joining from the current company's resume line."""
        if 'resume_line_ids' not in employee._fields:
            return ''
        resume_lines = employee.resume_line_ids.filtered(lambda l: l.date_start)
        if not resume_lines:
            return ''
        current = resume_lines.filtered(
            lambda l: l.name == employee.company_id.name)
        joining = (min(current.mapped('date_start')) if current
                   else max(resume_lines.mapped('date_start')))
        return joining.strftime('%d-%m-%Y')

    def _get_employee_branch(self, employee):
        if 'work_location_id' in employee._fields and employee.work_location_id:
            return employee.work_location_id.name or ''
        return ''
