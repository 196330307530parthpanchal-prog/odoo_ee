{
    'name': 'Ramsha Custom Label',
    'version': '19.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Custom 2x2 inch product label (category, barcode, name, size, price, company details)',
    'depends': ['product', 'stock'],
    'data': [
        'report/ars_label_reports.xml',
        'report/ars_label_templates.xml',
        'views/product_template_views.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
