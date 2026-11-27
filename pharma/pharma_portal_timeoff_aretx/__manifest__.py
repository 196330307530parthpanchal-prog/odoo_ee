{
    'name': 'Employee Apply Leave (Time Off)',
    'version': '1.1',
    'license': 'LGPL-3',
    'summary': 'Manage and apply leaves via portal user',
    "description":
        """
        """,
    'category': 'Pharma',
    'author': "Areterix Technologies",
    'website': 'https://www.areterix.com/',
    'depends': ['hr', 'portal', 'website', 'hr_holidays', 'hr_attendance'],
    'data': [
        #Security
        'security/ir.model.access.csv',
        'security/security.xml',

        #Views
        'views/employee_view.xml',
        'views/portal_time_off_templates.xml',
        'views/portal_balance_cards_templates.xml',
        'views/portal_attendance_templates.xml',
        'views/portal_ess_templates.xml',
        'views/portal_allocation_request_templates.xml',
        'views/portal_public_holidays_templates.xml',
        'views/portal_private_details_templates.xml',
        'views/private_request_views.xml',
        'views/portal_planned_activities_templates.xml',
    ],
    'images': ["static/description/icon.png"],
    'installable': True,
    'application': False,
    'auto_install': False,
}
