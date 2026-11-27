{
    'name': 'Pharma Planning Integration',
    'version': '18.0.3.0.0',
    'license': 'LGPL-3',
    'author': 'Areterix Technologies',
    'category': 'Human Resources',
    'summary': 'Use Odoo Planning as the source of employee shift assignments.',
    'depends': [
        'planning',
    ],
    'data': [
        'views/planning_slot_template.xml',
        'views/planning_slot.xml',
    ],
    'installable': True,
    'application': False,
}
