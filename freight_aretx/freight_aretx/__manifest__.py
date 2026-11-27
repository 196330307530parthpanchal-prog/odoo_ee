# -*- coding: utf-8 -*-
{
    'name': 'Shipping Charges',
    'version': '1.0',
    'category': 'Accounting',
    'summary': 'Custom invoice printing with service visibility control',
    'author': 'Areterix Technologies',
    'description': """
        This module adds:
        - Boolean field 'Visible on Print Invoice' in product service configuration
        - Conditional display of services in print invoice report based on the boolean field
    """,
        'author': 'Areterix Technologies',

    'website': 'https://www.yourcompany.com',
    'depends': [
        'base',
        'product',
        'account',
    ],
    'data': [
        'views/product_template_views.xml',
        'reports/invoice_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}