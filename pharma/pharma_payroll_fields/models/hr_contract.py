from odoo import fields, models


class HrContract(models.Model):
    _inherit = 'hr.contract'


    # Earnings / Salary Components
    pa_in_basic_salary = fields.Float(string='Basic Salary', default=0.0)
    pa_in_conveyance_allowance = fields.Float(string='Conveyance Allowance', default=0.0)
    pa_in_education_allowance = fields.Float(string='Education Allowance', default=0.0)
    pa_in_washing_allowance = fields.Float(string='Washing Allowance / Attire', default=0.0)
    pa_in_interim_bonus = fields.Float(string='Interim Bonus', default=0.0)
    pa_in_other_special_allowance = fields.Float(string='Other / Special Allowance', default=0.0)
    pa_in_fuel_allowance = fields.Float(string='Fuel Allowance', default=0.0)
    pa_in_professional_attire = fields.Float(string='Professional Attire', default=0.0)
    pa_in_official_client_meetings = fields.Float(string='Official Client Meetings', default=0.0)
    pa_in_pb_security = fields.Float(string='PB / Security', default=0.0)
    pa_in_performance_bonus = fields.Float(string='Performance Bonus', default=0.0)
    pa_in_arrear_amount = fields.Float(string='Arrear Amount', default=0.0)
    pa_in_additional_earnings = fields.Float(string='Interim / Additional Earnings', default=0.0)

    # Salary Calculation
    pa_in_sub_gross_salary = fields.Float(string='Sub Gross Salary', default=0.0)
    pa_in_total_gross_salary = fields.Float(string='Total Gross Salary', default=0.0)

    # Employer Liabilities / Company Contributions
    pa_in_employer_pf = fields.Float(string='Employer PF Contribution', default=0.0)
    pa_in_employer_esic = fields.Float(string='Employer ESIC Contribution', default=0.0)
    pa_in_employer_lwf = fields.Float(string='Employer LWF Contribution', default=0.0)
    pa_in_employer_leave_encashment = fields.Float(string='Employer Leave Encashment', default=0.0)
    pa_in_extra_curricular_charges = fields.Float(string='Employer Extra Curricular Charges', default=0.0)
    pa_in_employer_nps = fields.Float(string='Employer NPS Contribution (80CCD)', default=0.0)
    pa_in_employer_gratuity = fields.Float(string='Employer Gratuity Calculation', default=0.0)
    pa_in_employer_mediclaim = fields.Float(string='Employer Mediclaim Contribution', default=0.0)
    pa_in_employer_pf_rate = fields.Float(string='Employer PF Rate', default=0.0)
    pa_in_employer_esic_rate = fields.Float(string='Employer ESIC Rate', default=0.0)
    pa_in_employer_pf_basis = fields.Float(string='Employer PF Calculation Basis', default=0.0)

    # CTC Calculation
    pa_in_total_employer_liability = fields.Float(string='Total Employer Liability', default=0.0)
    pa_in_total_ctc = fields.Float(string='Total CTC', default=0.0)

    # Additional Employee Deductions
    pa_in_employee_lwf = fields.Float(string='Employee LWF', default=0.0)
    pa_in_bonus_recovery = fields.Float(string='Bonus Deduction / Recovery', default=0.0)
    pa_in_lta_recovery = fields.Float(string='LTA Recovery', default=0.0)
    pa_in_advance_salary = fields.Float(string='Advance Salary', default=0.0)
    pa_in_other_deduction = fields.Float(string='Other Deduction', default=0.0)
    pa_in_professional_tax = fields.Float(string='Professional Tax', default=0.0)
    pa_in_nps_deduction = fields.Float(string='NPS Deduction', default=0.0)
    pa_in_pb_security_recovery = fields.Float(string='PB / Security Recovery', default=0.0)

    # Final Salary Calculation
    pa_in_total_employee_deductions = fields.Float(string='Total Employee Deductions', default=0.0)
    pa_in_net_salary = fields.Float(string='Net Salary / Net Pay', default=0.0)
