{
    'name': 'Delivery Slip Signature Area',
    'version': '19.0.1.0.1',
    'category': 'Inventory/Inventory',
    'summary': 'Configurable signature area at the bottom of the delivery slip',
    'depends': ['account', 'stock'],
    'data': [
        'views/res_config_settings_views.xml',
        'report/report_deliveryslip.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}