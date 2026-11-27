{
    'name': 'Ramsha Invoice (ARETX)',
    'version': '19.0.1.3.0',
    'category': 'Accounting',
    'summary': 'Show POS receipt header address on customer invoice',
    'depends': ['account', 'point_of_sale', 'web'],
    'data': [
        # OLD (commented out): POS header text replacing the company address in the default layouts.
        # Company name and address are back to Odoo's default.
        'views/report_templates.xml',
        'views/invoice_report.xml',
        'data/gulf_vat_label.xml',  # Gulf countries: vat label "TRN"
        ],
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}