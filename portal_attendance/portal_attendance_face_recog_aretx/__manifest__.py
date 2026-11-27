{
    'name': 'Employee Portal Attendance with Selfie and live Location',
    'version': '2.0',
    'category': 'Human Resources',
    'summary': 'Portal check-in/check-out with a selfie and captured geo location',
    'description': """
Employee Portal Attendance (Selfie + Geo Location)
==================================================
* Portal users check in and check out from the portal home page.
* A face must be detected in the camera (detection only, no recognition) before
  attendance is submitted automatically.
* A selfie is captured from the camera on every check-in and check-out.
* The user's geo location is captured on every check-in and check-out
  (data only, no validation against locations or ranges).
* Selfie and coordinates are stored separately for check-in and check-out
  on the same hr.attendance record.
""",
    'author': 'Areterix Technologies',
    'website': 'https://www.areterix.com',
    'depends': ['hr_attendance', 'portal'],
    'data': [
        'views/attendance_admin_views.xml',
        'views/attendence_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'portal_attendance_face_recog_aretx/static/src/js/portal_attendance.js',
        ],
        'web.assets_backend': [
            'portal_attendance_face_recog_aretx/static/src/js/internal_attendance_face_gate.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
}
