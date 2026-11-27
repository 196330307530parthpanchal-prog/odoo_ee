{
    'name': 'Pharma Time Off 01 New',
    'version': '18.0.3.0.0',
    'category': 'Human Resources/Time Off',
    'author': 'Areterix Technologies',
    'summary': 'Custom Time Off restrictions and validations for Pharma',

    'depends': [
        'hr_holidays',
        # 'pharma_planning_aretx',
        'pharma_bioattendance_aretx',
    ],

    'data': [
        'security/security.xml',
        'views/hr_leave_types_view.xml',
    ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}