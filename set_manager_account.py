from getpass import getpass

from werkzeug.security import generate_password_hash

from app import Staff, app, db


name = input('Manager name: ').strip()
email = input('Manager email: ').strip()
password = getpass('Manager password: ')

if not name or not email:
    raise SystemExit('Name and email are required.')

if len(password) < 8:
    raise SystemExit('Password must contain at least 8 characters.')

with app.app_context():
    manager = Staff.query.filter_by(email=email).first()

    if manager:
        manager.name = name
        manager.password = generate_password_hash(password)
        manager.role = 'manager'
        message = 'Manager account updated successfully.'
    else:
        manager = Staff(
            name=name,
            email=email,
            password=generate_password_hash(password),
            role='manager',
        )
        db.session.add(manager)
        message = 'Manager account created successfully.'

    db.session.commit()
    print(message)
