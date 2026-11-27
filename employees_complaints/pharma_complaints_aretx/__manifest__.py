{
    'name': 'Pharma Complaints',
    'version': '1.0',
    'license': 'LGPL-3',
    'summary': 'Manage employee complaints and complaint types',
    'category': 'Pharma',
    'author': 'Areterix Technologies',
    'website': 'https://www.areterix.com/',
    'depends': ['hr','mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_complaint_views.xml',
        'views/hr_employee_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}