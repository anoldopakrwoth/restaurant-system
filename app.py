import os
import json
from functools import wraps
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime
from decimal import Decimal
from flask import Flask, request, jsonify, g, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

load_dotenv()

app = Flask(__name__)
cors_origins = [origin.strip() for origin in os.getenv(
    'CORS_ORIGINS', 'http://localhost:5500,http://127.0.0.1:5500,null'
).split(',') if origin.strip()]
CORS(app, origins=cors_origins)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-secret-key')
TOKEN_MAX_AGE = 60 * 60 * 8

ROLE_FEATURES = {
    'admin': {'dashboard', 'rooms', 'bookings', 'tables', 'orders', 'menu', 'customers', 'invoices', 'ai', 'staff'},
    'manager': {'dashboard', 'rooms', 'bookings', 'tables', 'orders', 'menu', 'customers', 'invoices', 'ai', 'staff'},
    'receptionist': {'dashboard', 'rooms', 'bookings', 'customers', 'ai'},
    'restaurant': {'dashboard', 'tables', 'orders', 'menu', 'ai'},
    'cashier': {'dashboard', 'orders', 'invoices', 'ai'},
    'housekeeping': {'dashboard', 'rooms', 'ai'},
}

def staff_required(view):
    """Require a valid staff bearer token for protected operational routes."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get('Authorization', '')
        if not header.startswith('Bearer '):
            return jsonify({'error': 'Staff authentication required'}), 401
        try:
            staff_id = URLSafeTimedSerializer(app.config['SECRET_KEY']).loads(
                header[7:], max_age=TOKEN_MAX_AGE
            )
        except (BadSignature, SignatureExpired):
            return jsonify({'error': 'Invalid or expired staff token'}), 401
        staff = db.session.get(Staff, int(staff_id))
        if not staff:
            return jsonify({'error': 'Staff account not found'}), 401
        g.current_staff = staff
        return view(*args, **kwargs)
    return wrapped

def role_required(*roles):
    """Require login plus one of the supplied staff roles."""
    def decorator(view):
        @staff_required
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.current_staff.role.lower() not in {role.lower() for role in roles}:
                return jsonify({'error': 'Your staff role is not allowed to perform this action'}), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator

def role_features(role):
    return sorted(ROLE_FEATURES.get((role or '').lower(), {'dashboard'}))

# Database Configuration (Reads MySQL from .env or defaults to SQLite)
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'hotel_restaurant_db')

# MySQL connection string fallback to SQLite
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


@app.get('/')
def dashboard():
    """Serve the staff dashboard from the same origin as the API."""
    return send_from_directory(app.root_path, 'index.html')


@app.get('/ai.js')
def dashboard_ai_script():
    return send_from_directory(app.root_path, 'ai.js')


@app.get('/styles.css')
def dashboard_stylesheet():
    return send_from_directory(app.root_path, 'styles.css')


@app.get('/background.jpg/<path:filename>')
def dashboard_image(filename):
    return send_from_directory(os.path.join(app.root_path, 'background.jpg'), filename)

ROOM_STATUSES = {'available', 'occupied', 'maintenance'}
TABLE_STATUSES = {'available', 'occupied', 'reserved'}
BOOKING_STATUSES = {'confirmed', 'checked_in', 'completed', 'cancelled'}
ORDER_STATUSES = {'pending', 'served', 'paid', 'cancelled'}
PAYMENT_STATUSES = {'pending', 'paid', 'failed'}

def _ai_context():
    """Small, safe operational snapshot supplied to the AI on each request."""
    rooms = Room.query.all()
    tables = RestaurantTable.query.all()
    menu = MenuItem.query.filter_by(is_available=True).all()
    bookings = Booking.query.order_by(Booking.check_in.desc()).limit(20).all()
    orders = DiningOrder.query.order_by(DiningOrder.order_time.desc()).limit(20).all()
    invoices = Invoice.query.order_by(Invoice.created_at.desc()).limit(20).all()
    return {
        'rooms': [{'id': r.room_id, 'number': r.room_number, 'type': r.room_type,
                   'price': float(r.price_per_night), 'status': r.status} for r in rooms],
        'tables': [{'id': t.table_id, 'number': t.table_number,
                    'capacity': t.capacity, 'status': t.status} for t in tables],
        'available_menu': [{'id': m.menu_item_id, 'name': m.name,
                            'category': m.category, 'price': float(m.price)} for m in menu],
        'recent_bookings': [{'id': b.booking_id, 'customer_id': b.customer_id,
                             'room_id': b.room_id, 'check_in': b.check_in.isoformat(),
                             'check_out': b.check_out.isoformat(), 'status': b.booking_status,
                             'total': float(b.total_price)} for b in bookings],
        'recent_orders': [{'id': o.order_id, 'status': o.order_status,
                           'customer_id': o.customer_id, 'table_id': o.table_id,
                           'room_id': o.room_id} for o in orders],
        'recent_invoices': [{'id': i.invoice_id, 'total': float(i.grand_total),
                             'status': i.payment_status, 'method': i.payment_method} for i in invoices]
    }

def _local_ai_answer(message, context):
    text = message.lower()
    rooms = context['rooms']
    tables = context['tables']
    if any(word in text for word in ('room', 'rooms')):
        available = [r for r in rooms if r['status'] == 'available']
        return f"There are {len(available)} available rooms out of {len(rooms)} total."
    if any(word in text for word in ('table', 'tables')):
        available = [t for t in tables if t['status'] == 'available']
        return f"There are {len(available)} open tables out of {len(tables)} total."
    if 'menu' in text or 'food' in text:
        names = ', '.join(item['name'] for item in context['available_menu'][:8]) or 'no available items'
        return f"Available menu items include: {names}."
    if 'booking' in text or 'reservation' in text:
        return f"I can see {len(context['recent_bookings'])} recent bookings."
    if 'order' in text:
        return f"I can see {len(context['recent_orders'])} recent orders."
    return "I’m connected to rooms, bookings, tables, menu, orders, and invoices. Ask me about availability, sales operations, or a guest action."

@app.get('/api/health')
def health_check():
    return jsonify({'status': 'ok', 'service': 'hotel-restaurant-api', 'ai_configured': bool(os.getenv('OPENAI_API_KEY'))})

@app.post('/api/ai/chat')
@staff_required
def ai_chat():
    """Unified AI gateway for the dashboard and other clients.

    Set OPENAI_API_KEY to use a hosted model. Without it, a local data-aware
    fallback answers common operational questions.
    """
    data = request.get_json(silent=True) or {}
    message = str(data.get('message', '')).strip()
    if not message:
        return jsonify({'error': 'message is required'}), 400
    context = _ai_context()
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return jsonify({'answer': _local_ai_answer(message, context), 'source': 'local', 'context': context})

    model = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
    payload = {'model': model, 'temperature': 0.2, 'messages': [
        {'role': 'system', 'content': 'You are the operations assistant for Java House hotel and restaurant. Answer using only the supplied live data. Be concise. Never invent records, prices, or availability.'},
        {'role': 'user', 'content': json.dumps({'question': message, 'live_data': context})}
    ]}
    req = Request('https://api.openai.com/v1/chat/completions',
                  data=json.dumps(payload).encode('utf-8'),
                  headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
        answer = result['choices'][0]['message']['content']
        return jsonify({'answer': answer, 'source': 'openai', 'model': model})
    except (HTTPError, URLError, KeyError, ValueError) as exc:
        app.logger.warning('AI provider unavailable: %s', exc)
        return jsonify({'answer': _local_ai_answer(message, context), 'source': 'local_fallback', 'warning': 'AI provider unavailable'})

# ==========================================
# DATABASE MODELS (Matching ER Diagram)
# ==========================================

class Staff(db.Model):
    __tablename__ = 'staff'
    staff_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Customer(db.Model):
    __tablename__ = 'customers'
    customer_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Room(db.Model):
    __tablename__ = 'rooms'
    room_id = db.Column(db.Integer, primary_key=True)
    room_number = db.Column(db.String(10), unique=True, nullable=False)
    room_type = db.Column(db.String(50), nullable=False)
    price_per_night = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default='available')  # available, occupied, maintenance

class Booking(db.Model):
    __tablename__ = 'bookings'
    booking_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=False)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id'), nullable=False)
    check_in = db.Column(db.DateTime, nullable=False)
    check_out = db.Column(db.DateTime, nullable=False)
    booking_status = db.Column(db.String(20), default='confirmed')
    total_price = db.Column(db.Numeric(10, 2), nullable=False)

class RestaurantTable(db.Model):
    __tablename__ = 'restaurant_tables'
    table_id = db.Column(db.Integer, primary_key=True)
    table_number = db.Column(db.String(10), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='available')  # available, occupied, reserved

class MenuItem(db.Model):
    __tablename__ = 'menu_items'
    menu_item_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_available = db.Column(db.Boolean, default=True)

class DiningOrder(db.Model):
    __tablename__ = 'dining_orders'
    order_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=True)
    table_id = db.Column(db.Integer, db.ForeignKey('restaurant_tables.table_id'), nullable=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.room_id'), nullable=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('staff.staff_id'), nullable=True)
    order_status = db.Column(db.String(20), default='pending')  # pending, served, paid, cancelled
    order_time = db.Column(db.DateTime, default=datetime.utcnow)

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    order_item_id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('dining_orders.order_id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_items.menu_item_id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)

class Invoice(db.Model):
    __tablename__ = 'invoices'
    invoice_id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.customer_id'), nullable=False)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.booking_id'), nullable=True)
    grand_total = db.Column(db.Numeric(10, 2), nullable=False)
    payment_status = db.Column(db.String(20), default='pending')  # pending, paid, failed
    payment_method = db.Column(db.String(50))  # cash, mobile_money, credit_card
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables automatically on launch
with app.app_context():
    db.create_all()

# ==========================================
# API ENDPOINTS
# ==========================================

# 0. STAFF ACCESS
@app.get('/api/staff')
@role_required('admin', 'manager')
def list_staff():
    return jsonify([{
        'staff_id': staff.staff_id,
        'name': staff.name,
        'email': staff.email,
        'role': staff.role,
        'features': role_features(staff.role),
        'created_at': staff.created_at.isoformat() if staff.created_at else None,
    } for staff in Staff.query.order_by(Staff.created_at.desc()).all()])

@app.route('/api/staff/register', methods=['POST'])
@role_required('admin', 'manager')
def register_staff():
    data = request.json or {}
    required = ('name', 'email', 'password', 'role')
    if any(not data.get(key) for key in required):
        return jsonify({'error': 'name, email, password and role are required'}), 400
    if Staff.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'A staff account with that email already exists'}), 409
    requested_role = str(data['role']).strip().lower()
    if requested_role not in ROLE_FEATURES:
        return jsonify({'error': 'Invalid staff role'}), 400
    staff = Staff(name=data['name'], email=data['email'],
                  password=generate_password_hash(data['password']), role=requested_role)
    db.session.add(staff)
    db.session.commit()
    return jsonify({'message': 'Staff account created', 'staff_id': staff.staff_id}), 201

@app.put('/api/staff/<int:staff_id>')
@role_required('admin', 'manager')
def update_staff(staff_id):
    staff = db.session.get(Staff, staff_id)
    if not staff:
        return jsonify({'error': 'Staff account not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'name' in data and str(data['name']).strip():
        staff.name = str(data['name']).strip()
    if 'email' in data and str(data['email']).strip():
        duplicate = Staff.query.filter(Staff.email == str(data['email']).strip(), Staff.staff_id != staff_id).first()
        if duplicate:
            return jsonify({'error': 'That email is already assigned to another staff account'}), 409
        staff.email = str(data['email']).strip()
    if 'role' in data:
        requested_role = str(data['role']).strip().lower()
        if requested_role not in ROLE_FEATURES:
            return jsonify({'error': 'Invalid staff role'}), 400
        staff.role = requested_role
    if data.get('password'):
        staff.password = generate_password_hash(data['password'])
    db.session.commit()
    return jsonify({'message': 'Staff account updated', 'staff_id': staff.staff_id})

@app.delete('/api/staff/<int:staff_id>')
@role_required('admin', 'manager')
def delete_staff(staff_id):
    staff = db.session.get(Staff, staff_id)
    if not staff:
        return jsonify({'error': 'Staff account not found'}), 404
    if staff.staff_id == g.current_staff.staff_id:
        return jsonify({'error': 'You cannot delete the account you are currently using'}), 400
    for order in DiningOrder.query.filter_by(staff_id=staff_id).all():
        order.staff_id = None
    db.session.delete(staff)
    db.session.commit()
    return jsonify({'message': 'Staff account deleted', 'staff_id': staff_id})

@app.route('/api/staff/login', methods=['POST'])
def login_staff():
    data = request.json or {}
    staff = Staff.query.filter_by(email=data.get('email')).first()
    try:
        valid_password = bool(staff and check_password_hash(staff.password, data.get('password', '')))
    except (TypeError, ValueError):
        # Protect login from legacy or manually-created records with invalid hashes.
        valid_password = False
    if not valid_password:
        return jsonify({'error': 'Invalid email or password'}), 401
    token = URLSafeTimedSerializer(app.config['SECRET_KEY']).dumps(str(staff.staff_id))
    return jsonify({'staff_id': staff.staff_id, 'name': staff.name, 'email': staff.email,
                    'role': staff.role, 'features': role_features(staff.role),
                    'token': token, 'expires_in': TOKEN_MAX_AGE})

@app.get('/api/staff/me')
@staff_required
def current_staff():
    staff = g.current_staff
    return jsonify({'staff_id': staff.staff_id, 'name': staff.name,
                    'email': staff.email, 'role': staff.role,
                    'features': role_features(staff.role)})

# 1. CUSTOMERS
@app.route('/api/customers', methods=['POST'])
@role_required('admin', 'manager', 'receptionist')
def create_customer():
    data = request.json
    customer = Customer(
        first_name=data['first_name'],
        last_name=data['last_name'],
        phone=data.get('phone'),
        email=data.get('email')
    )
    db.session.add(customer)
    db.session.commit()
    return jsonify({'message': 'Customer registered', 'customer_id': customer.customer_id}), 201

@app.route('/api/customers', methods=['GET'])
@role_required('admin', 'manager', 'receptionist')
def get_customers():
    customers = Customer.query.all()
    return jsonify([{
        'customer_id': c.customer_id,
        'first_name': c.first_name,
        'last_name': c.last_name,
        'phone': c.phone,
        'email': c.email
    } for c in customers])

# 2. ROOMS & BOOKINGS
@app.route('/api/rooms', methods=['GET', 'POST'])
@role_required('admin', 'manager', 'receptionist', 'housekeeping')
def manage_rooms():
    if request.method == 'POST':
        data = request.json
        if data.get('status', 'available') not in ROOM_STATUSES:
            return jsonify({'error': 'Invalid room status'}), 400
        if Room.query.filter_by(room_number=data.get('room_number')).first():
            return jsonify({'error': 'Room number already exists'}), 409
        room = Room(
            room_number=data['room_number'],
            room_type=data['room_type'],
            price_per_night=data['price_per_night'],
            status=data.get('status', 'available')
        )
        db.session.add(room)
        db.session.commit()
        return jsonify({'message': 'Room added', 'room_id': room.room_id}), 201

    rooms = Room.query.all()
    return jsonify([{
        'room_id': r.room_id,
        'room_number': r.room_number,
        'room_type': r.room_type,
        'price_per_night': float(r.price_per_night),
        'status': r.status
    } for r in rooms])

@app.route('/api/bookings', methods=['GET', 'POST'])
@role_required('admin', 'manager', 'receptionist')
def create_booking():
    if request.method == 'GET':
        bookings = Booking.query.order_by(Booking.check_in.desc()).all()
        return jsonify([{
            'booking_id': b.booking_id, 'customer_id': b.customer_id, 'room_id': b.room_id,
            'check_in': b.check_in.isoformat(), 'check_out': b.check_out.isoformat(),
            'booking_status': b.booking_status, 'total_price': float(b.total_price)
        } for b in bookings])
    data = request.json
    check_in = datetime.fromisoformat(data['check_in'])
    check_out = datetime.fromisoformat(data['check_out'])

    customer = db.session.get(Customer, data.get('customer_id'))
    room = db.session.get(Room, data.get('room_id'))
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    if room.status != 'available':
        return jsonify({'error': 'Room is not available'}), 409
    if check_out <= check_in:
        return jsonify({'error': 'Check-out must be after check-in'}), 400

    # Calculate night duration and total room price
    nights = max((check_out - check_in).days, 1)
    total_price = room.price_per_night * nights

    booking = Booking(
        customer_id=data['customer_id'],
        room_id=data['room_id'],
        check_in=check_in,
        check_out=check_out,
        booking_status=data.get('booking_status', 'confirmed'),
        total_price=total_price
    )

    room.status = 'occupied'
    db.session.add(booking)
    db.session.commit()
    return jsonify({'message': 'Booking confirmed', 'booking_id': booking.booking_id, 'total_price': float(total_price)}), 201

# 3. RESTAURANT TABLES & MENU
@app.route('/api/tables', methods=['GET', 'POST'])
@role_required('admin', 'manager', 'restaurant')
def manage_tables():
    if request.method == 'POST':
        data = request.json
        if data.get('status', 'available') not in TABLE_STATUSES:
            return jsonify({'error': 'Invalid table status'}), 400
        if RestaurantTable.query.filter_by(table_number=data.get('table_number')).first():
            return jsonify({'error': 'Table number already exists'}), 409
        table = RestaurantTable(
            table_number=data['table_number'],
            capacity=data['capacity'],
            status=data.get('status', 'available')
        )
        db.session.add(table)
        db.session.commit()
        return jsonify({'message': 'Table added', 'table_id': table.table_id}), 201

    tables = RestaurantTable.query.all()
    return jsonify([{
        'table_id': t.table_id,
        'table_number': t.table_number,
        'capacity': t.capacity,
        'status': t.status
    } for t in tables])

@app.route('/api/menu', methods=['GET', 'POST'])
@role_required('admin', 'manager', 'restaurant')
def manage_menu():
    if request.method == 'POST':
        data = request.json
        if not data.get('name') or not data.get('category') or data.get('price') is None:
            return jsonify({'error': 'name, category and price are required'}), 400
        if float(data['price']) < 0:
            return jsonify({'error': 'Price cannot be negative'}), 400
        item = MenuItem(
            name=data['name'],
            category=data['category'],
            price=data['price'],
            is_available=data.get('is_available', True)
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({'message': 'Menu item added', 'menu_item_id': item.menu_item_id}), 201

    items = MenuItem.query.all()
    return jsonify([{
        'menu_item_id': m.menu_item_id,
        'name': m.name,
        'category': m.category,
        'price': float(m.price),
        'is_available': m.is_available
    } for m in items])

# 4. DINING ORDERS & ORDER ITEMS
@app.route('/api/orders', methods=['GET', 'POST'])
@role_required('admin', 'manager', 'restaurant', 'cashier')
def place_order():
    if request.method == 'GET':
        orders = DiningOrder.query.order_by(DiningOrder.order_time.desc()).all()
        return jsonify([{
            'order_id': o.order_id, 'customer_id': o.customer_id, 'table_id': o.table_id,
            'room_id': o.room_id, 'staff_id': o.staff_id, 'order_status': o.order_status,
            'order_time': o.order_time.isoformat()
        } for o in orders])
    data = request.json
    if data.get('order_status', 'pending') not in ORDER_STATUSES:
        return jsonify({'error': 'Invalid order status'}), 400
    if not data.get('items'):
        return jsonify({'error': 'At least one order item is required'}), 400
    if data.get('customer_id') and not db.session.get(Customer, data['customer_id']):
        return jsonify({'error': 'Customer not found'}), 404
    if data.get('table_id') and not db.session.get(RestaurantTable, data['table_id']):
        return jsonify({'error': 'Table not found'}), 404
    if data.get('room_id') and not db.session.get(Room, data['room_id']):
        return jsonify({'error': 'Room not found'}), 404
    order = DiningOrder(
        customer_id=data.get('customer_id'),
        table_id=data.get('table_id'),
        room_id=data.get('room_id'),
        staff_id=data.get('staff_id'),
        order_status=data.get('order_status', 'pending')
    )
    db.session.add(order)
    db.session.flush()

    # Save ordered items
    for item in data.get('items', []):
        menu_item = db.session.get(MenuItem, item.get('menu_item_id'))
        if not menu_item:
            return jsonify({'error': 'Menu item not found'}), 404
        if int(item.get('quantity', 0)) < 1:
            return jsonify({'error': 'Quantity must be at least 1'}), 400
        order_item = OrderItem(
            order_id=order.order_id,
            menu_item_id=item['menu_item_id'],
            quantity=item['quantity'],
            unit_price=item['unit_price']
        )
        db.session.add(order_item)

    if data.get('table_id'):
        table = RestaurantTable.query.get(data['table_id'])
        if table:
            table.status = 'occupied'

    db.session.commit()
    return jsonify({'message': 'Order created', 'order_id': order.order_id}), 201

# 5. INVOICES & CHECKOUT
@app.route('/api/invoices', methods=['GET', 'POST'])
@role_required('admin', 'manager', 'cashier')
def create_invoice():
    if request.method == 'GET':
        invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
        return jsonify([{
            'invoice_id': i.invoice_id, 'customer_id': i.customer_id, 'booking_id': i.booking_id,
            'grand_total': float(i.grand_total), 'payment_status': i.payment_status,
            'payment_method': i.payment_method, 'created_at': i.created_at.isoformat()
        } for i in invoices])
    data = request.json
    if not db.session.get(Customer, data.get('customer_id')):
        return jsonify({'error': 'Customer not found'}), 404
    if float(data.get('grand_total', -1)) < 0:
        return jsonify({'error': 'Grand total cannot be negative'}), 400
    if data.get('payment_status', 'paid') not in PAYMENT_STATUSES:
        return jsonify({'error': 'Invalid payment status'}), 400
    invoice = Invoice(
        customer_id=data['customer_id'],
        booking_id=data.get('booking_id'),
        grand_total=data['grand_total'],
        payment_status=data.get('payment_status', 'paid'),
        payment_method=data.get('payment_method', 'cash')
    )

    # Update room or table states if associated
    if data.get('booking_id'):
        booking = Booking.query.get(data['booking_id'])
        if booking:
            booking.booking_status = 'completed'
            room = Room.query.get(booking.room_id)
            if room:
                room.status = 'available'

    db.session.add(invoice)
    db.session.commit()
    return jsonify({'message': 'Invoice settled', 'invoice_id': invoice.invoice_id}), 201

# 6. CONTROLLED UPDATES (records are deactivated/status-updated, not destroyed)
@app.route('/api/rooms/<int:room_id>', methods=['PUT'])
@role_required('admin', 'manager', 'housekeeping')
def update_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'status' in data and data['status'] not in ROOM_STATUSES:
        return jsonify({'error': 'Invalid room status'}), 400
    for field in ('room_number', 'room_type', 'price_per_night', 'status'):
        if field in data:
            setattr(room, field, data[field])
    db.session.commit()
    return jsonify({'message': 'Room updated', 'room_id': room.room_id})

@app.route('/api/tables/<int:table_id>', methods=['PUT'])
@role_required('admin', 'manager', 'restaurant')
def update_table(table_id):
    table = db.session.get(RestaurantTable, table_id)
    if not table:
        return jsonify({'error': 'Table not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'status' in data and data['status'] not in TABLE_STATUSES:
        return jsonify({'error': 'Invalid table status'}), 400
    for field in ('table_number', 'capacity', 'status'):
        if field in data:
            setattr(table, field, data[field])
    db.session.commit()
    return jsonify({'message': 'Table updated', 'table_id': table.table_id})

@app.route('/api/menu/<int:menu_item_id>', methods=['PUT'])
@role_required('admin', 'manager', 'restaurant')
def update_menu_item(menu_item_id):
    item = db.session.get(MenuItem, menu_item_id)
    if not item:
        return jsonify({'error': 'Menu item not found'}), 404
    data = request.get_json(silent=True) or {}
    for field in ('name', 'category', 'price', 'is_available'):
        if field in data:
            setattr(item, field, data[field])
    db.session.commit()
    return jsonify({'message': 'Menu item updated', 'menu_item_id': item.menu_item_id})

@app.route('/api/bookings/<int:booking_id>', methods=['PUT'])
@role_required('admin', 'manager', 'receptionist')
def update_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    data = request.get_json(silent=True) or {}
    if 'booking_status' in data and data['booking_status'] not in BOOKING_STATUSES:
        return jsonify({'error': 'Invalid booking status'}), 400
    if 'booking_status' in data:
        booking.booking_status = data['booking_status']
        if data['booking_status'] in ('completed', 'cancelled'):
            room = db.session.get(Room, booking.room_id)
            if room:
                room.status = 'available'
    db.session.commit()
    return jsonify({'message': 'Booking updated', 'booking_id': booking.booking_id})

@app.route('/api/orders/<int:order_id>', methods=['PUT'])
@role_required('admin', 'manager', 'restaurant', 'cashier')
def update_order(order_id):
    order = db.session.get(DiningOrder, order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    data = request.get_json(silent=True) or {}
    if data.get('order_status') not in ORDER_STATUSES:
        return jsonify({'error': 'A valid order_status is required'}), 400
    order.order_status = data['order_status']
    db.session.commit()
    return jsonify({'message': 'Order updated', 'order_id': order.order_id})

@app.route('/api/invoices/<int:invoice_id>', methods=['PUT'])
@role_required('admin', 'manager', 'cashier')
def update_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    data = request.get_json(silent=True) or {}
    if data.get('payment_status') not in PAYMENT_STATUSES:
        return jsonify({'error': 'A valid payment_status is required'}), 400
    invoice.payment_status = data['payment_status']
    if 'payment_method' in data:
        invoice.payment_method = data['payment_method']
    db.session.commit()
    return jsonify({'message': 'Invoice updated', 'invoice_id': invoice.invoice_id})

# 7. DIRECT RECORD MANAGEMENT
# Deletes are explicit and checked for related records so a manager cannot
# accidentally orphan bookings, orders, or invoices.
@app.put('/api/customers/<int:customer_id>')
@role_required('admin', 'manager', 'receptionist')
def update_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    data = request.get_json(silent=True) or {}
    for field in ('first_name', 'last_name', 'phone', 'email'):
        if field in data:
            setattr(customer, field, data[field])
    db.session.commit()
    return jsonify({'message': 'Customer updated', 'customer_id': customer_id})

@app.delete('/api/customers/<int:customer_id>')
@role_required('admin', 'manager', 'receptionist')
def delete_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return jsonify({'error': 'Customer not found'}), 404
    if (Booking.query.filter_by(customer_id=customer_id).first() or
            DiningOrder.query.filter_by(customer_id=customer_id).first() or
            Invoice.query.filter_by(customer_id=customer_id).first()):
        return jsonify({'error': 'Customer cannot be deleted while bookings, orders, or invoices reference it'}), 409
    db.session.delete(customer)
    db.session.commit()
    return jsonify({'message': 'Customer deleted', 'customer_id': customer_id})

@app.delete('/api/rooms/<int:room_id>')
@role_required('admin', 'manager', 'housekeeping')
def delete_room(room_id):
    room = db.session.get(Room, room_id)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    if Booking.query.filter_by(room_id=room_id).first() or DiningOrder.query.filter_by(room_id=room_id).first():
        return jsonify({'error': 'Room cannot be deleted while bookings or orders reference it'}), 409
    db.session.delete(room)
    db.session.commit()
    return jsonify({'message': 'Room deleted', 'room_id': room_id})

@app.delete('/api/tables/<int:table_id>')
@role_required('admin', 'manager', 'restaurant')
def delete_table(table_id):
    table = db.session.get(RestaurantTable, table_id)
    if not table:
        return jsonify({'error': 'Table not found'}), 404
    if DiningOrder.query.filter_by(table_id=table_id).first():
        return jsonify({'error': 'Table cannot be deleted while orders reference it'}), 409
    db.session.delete(table)
    db.session.commit()
    return jsonify({'message': 'Table deleted', 'table_id': table_id})

@app.delete('/api/menu/<int:menu_item_id>')
@role_required('admin', 'manager', 'restaurant')
def delete_menu_item(menu_item_id):
    item = db.session.get(MenuItem, menu_item_id)
    if not item:
        return jsonify({'error': 'Menu item not found'}), 404
    if OrderItem.query.filter_by(menu_item_id=menu_item_id).first():
        return jsonify({'error': 'Menu item cannot be deleted while order history references it; mark it unavailable instead'}), 409
    db.session.delete(item)
    db.session.commit()
    return jsonify({'message': 'Menu item deleted', 'menu_item_id': menu_item_id})

@app.delete('/api/bookings/<int:booking_id>')
@role_required('admin', 'manager', 'receptionist')
def delete_booking(booking_id):
    booking = db.session.get(Booking, booking_id)
    if not booking:
        return jsonify({'error': 'Booking not found'}), 404
    if Invoice.query.filter_by(booking_id=booking_id).first():
        return jsonify({'error': 'Booking cannot be deleted while an invoice references it'}), 409
    db.session.delete(booking)
    db.session.commit()
    return jsonify({'message': 'Booking deleted', 'booking_id': booking_id})

@app.delete('/api/orders/<int:order_id>')
@role_required('admin', 'manager', 'restaurant', 'cashier')
def delete_order(order_id):
    order = db.session.get(DiningOrder, order_id)
    if not order:
        return jsonify({'error': 'Order not found'}), 404
    OrderItem.query.filter_by(order_id=order_id).delete(synchronize_session=False)
    db.session.delete(order)
    db.session.commit()
    return jsonify({'message': 'Order deleted', 'order_id': order_id})

@app.delete('/api/invoices/<int:invoice_id>')
@role_required('admin', 'manager', 'cashier')
def delete_invoice(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({'error': 'Invoice not found'}), 404
    db.session.delete(invoice)
    db.session.commit()
    return jsonify({'message': 'Invoice deleted', 'invoice_id': invoice_id})

if __name__ == '__main__':
    app.run(
        host=os.getenv('HOST', '127.0.0.1'),
        port=int(os.getenv('PORT', '5000')),
        debug=os.getenv('FLASK_DEBUG', '0').lower() in {'1', 'true', 'yes'},
    )
