from getpass import getpass

from werkzeug.security import generate_password_hash

from app import Staff, app, db


email = input('Staff email: ').strip()
password = getpass('New password: ')

if len(password) < 8:
    raise SystemExit('Password must contain at least 8 characters.')

with app.app_context():
    staff = Staff.query.filter_by(email=email).first()
    if not staff:
        name = input('Staff name: ').strip()
        staff = Staff(
            name=name,
            email=email,
            password=generate_password_hash(password),
            role='admin',
        )
        db.session.add(staff)
        message = 'Admin staff account created.'
    else:
        staff.password = generate_password_hash(password)
        message = 'Staff password reset successfully.'
    db.session.commit()
    print(message)
