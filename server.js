const express = require('express');
const cors = require('cors');
const db = require('./db');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
require('dotenv').config();

const app = express();
app.use(cors());
app.use(express.json());

// --- AUTHENTICATION MIDDLEWARE ---
const authenticateToken = (req, res, next) => {
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1]; // Expecting "Bearer <TOKEN>"

  if (!token) return res.status(401).json({ error: 'Access denied. No token provided.' });

  jwt.verify(token, process.env.JWT_SECRET || 'fallback_secret', (err, user) => {
    if (err) return res.status(403).json({ error: 'Invalid or expired token.' });
    req.user = user;
    next();
  });
};

const authorizeRoles = (...allowedRoles) => {
  return (req, res, next) => {
    if (!req.user || !allowedRoles.includes(req.user.role)) {
      return res.status(403).json({ error: 'Forbidden: Insufficient permissions.' });
    }
    next();
  };
};

// --- AUTH ROUTES ---

// Register Staff Account
app.post('/api/auth/register', async (req, res) => {
  const { name, email, password, role } = req.body;
  if (!name || !email || !password) {
    return res.status(400).json({ error: 'Name, email, and password are required.' });
  }

  try {
    const hashedPassword = await bcrypt.hash(password, 10);
    const [result] = await db.query(
      'INSERT INTO staff (name, email, password, role) VALUES (?, ?, ?, ?)',
      [name, email, hashedPassword, role || 'waiter']
    );

    res.status(201).json({ message: 'Staff account created successfully.', staff_id: result.insertId });
  } catch (err) {
    console.error('Registration Error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// Staff Login
app.post('/api/auth/login', async (req, res) => {
  const { email, password } = req.body;
  if (!email || !password) {
    return res.status(400).json({ error: 'Email and password are required.' });
  }

  try {
    const [rows] = await db.query('SELECT * FROM staff WHERE email = ?', [email]);
    if (rows.length === 0) return res.status(400).json({ error: 'Invalid email or password.' });

    const staffMember = rows[0];
    const validPassword = await bcrypt.compare(password, staffMember.password);
    if (!validPassword) return res.status(400).json({ error: 'Invalid email or password.' });

    const token = jwt.sign(
      { staff_id: staffMember.staff_id, role: staffMember.role, name: staffMember.name },
      process.env.JWT_SECRET || 'fallback_secret',
      { expiresIn: '8h' }
    );

    res.json({
      message: 'Login successful',
      token,
      user: { staff_id: staffMember.staff_id, name: staffMember.name, role: staffMember.role }
    });
  } catch (err) {
    console.error('Login Error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// --- CORE SYSTEM ROUTES ---

// Base Route
app.get('/', (req, res) => {
  res.send('Hotel & Restaurant Management API is online.');
});

// 1. GET: Fetch all rooms (Public/Staff access)
app.get('/api/rooms', async (req, res) => {
  try {
    const [rooms] = await db.query('SELECT * FROM rooms');
    res.json(rooms);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 2. GET: Fetch active menu items (Public/Staff access)
app.get('/api/menu', async (req, res) => {
  try {
    const [menu] = await db.query('SELECT * FROM menu_items WHERE is_available = TRUE');
    res.json(menu);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 3. POST: Book a room (Protected: Receptionist & Manager)
app.post('/api/bookings', authenticateToken, authorizeRoles('receptionist', 'manager'), async (req, res) => {
  const { customer_id, room_id, check_in, check_out, total_price } = req.body;
  const connection = await db.getConnection();
  try {
    await connection.beginTransaction();

    const [booking] = await connection.query(
      'INSERT INTO bookings (customer_id, room_id, check_in, check_out, booking_status, total_price) VALUES (?, ?, ?, ?, "checked_in", ?)',
      [customer_id, room_id, check_in, check_out, total_price]
    );

    await connection.query('UPDATE rooms SET status = "occupied" WHERE room_id = ?', [room_id]);

    await connection.commit();
    res.status(201).json({ message: 'Room booked successfully', booking_id: booking.insertId });
  } catch (err) {
    await connection.rollback();
    res.status(500).json({ error: err.message });
  } finally {
    connection.release();
  }
});

// 4. POST: Place a restaurant POS order (Protected: Waiter & Manager)
app.post('/api/orders', authenticateToken, authorizeRoles('waiter', 'manager'), async (req, res) => {
  const { customer_id, table_id, room_id, items } = req.body;
  const staff_id = req.user.staff_id; // Automatically pulled from JWT payload
  const connection = await db.getConnection();
  try {
    await connection.beginTransaction();

    const [order] = await connection.query(
      'INSERT INTO dining_orders (customer_id, table_id, room_id, staff_id, order_status) VALUES (?, ?, ?, ?, "pending")',
      [customer_id || null, table_id || null, room_id || null, staff_id]
    );
    const orderId = order.insertId;

    if (items && items.length > 0) {
      for (let item of items) {
        await connection.query(
          'INSERT INTO order_items (order_id, menu_item_id, quantity, unit_price) VALUES (?, ?, ?, ?)',
          [orderId, item.menu_item_id, item.quantity, item.unit_price]
        );
      }
    }

    await connection.commit();
    res.status(201).json({ message: 'Order created', order_id: orderId });
  } catch (err) {
    await connection.rollback();
    res.status(500).json({ error: err.message });
  } finally {
    connection.release();
  }
});

// 5. GET: Calculate checkout bill for a guest
app.get('/api/checkout/:customer_id', async (req, res) => {
  const { customer_id } = req.params;
  try {
    const [roomSubtotal] = await db.query(
      'SELECT SUM(total_price) as total FROM bookings WHERE customer_id = ? AND booking_status = "checked_in"',
      [customer_id]
    );
    const [diningSubtotal] = await db.query(
      `SELECT SUM(oi.quantity * oi.unit_price) as total 
       FROM dining_orders o 
       JOIN order_items oi ON o.order_id = oi.order_id 
       WHERE o.customer_id = ? AND o.order_status != "cancelled"`,
      [customer_id]
    );

    const roomTotal = parseFloat(roomSubtotal[0].total || 0);
    const diningTotal = parseFloat(diningSubtotal[0].total || 0);

    res.json({
      customer_id: parseInt(customer_id),
      room_total: roomTotal,
      dining_total: diningTotal,
      grand_total: roomTotal + diningTotal
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// 6. POST: Process payment and check-out guest (Protected: Receptionist & Manager)
app.post('/api/checkout', authenticateToken, authorizeRoles('receptionist', 'manager'), async (req, res) => {
  const { customer_id, booking_id, payment_method, amount_paid } = req.body;

  if (!customer_id || !booking_id || amount_paid === undefined) {
    return res.status(400).json({ error: 'Missing required parameters.' });
  }

  const connection = await db.getConnection();

  try {
    await connection.beginTransaction();

    const [bookingExists] = await connection.query(
      'SELECT room_id FROM bookings WHERE booking_id = ? AND customer_id = ?',
      [booking_id, customer_id]
    );

    if (bookingExists.length === 0) {
      await connection.rollback();
      return res.status(404).json({ error: `Booking ID ${booking_id} for Customer ID ${customer_id} not found.` });
    }

    const targetRoomId = bookingExists[0].room_id;

    await connection.query(
      'UPDATE bookings SET booking_status = "checked_out" WHERE booking_id = ?',
      [booking_id]
    );

    await connection.query(
      'UPDATE rooms SET status = "cleaning" WHERE room_id = ?',
      [targetRoomId]
    );

    await connection.query(
      'INSERT INTO invoices (customer_id, booking_id, grand_total, payment_status, payment_method) VALUES (?, ?, ?, "paid", ?)',
      [customer_id, booking_id, amount_paid, payment_method || 'cash']
    );

    await connection.commit();
    res.json({ message: 'Check-out complete! Room marked for cleaning.' });
  } catch (err) {
    await connection.rollback();
    res.status(500).json({ error: err.message });
  } finally {
    connection.release();
  }
});

// 7. PATCH: Housekeeping status update
app.patch('/api/rooms/:id/status', authenticateToken, async (req, res) => {
  const { id } = req.params;
  const { status } = req.body;
  try {
    await db.query('UPDATE rooms SET status = ? WHERE room_id = ?', [status, id]);
    res.json({ message: `Room status updated to ${status}` });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 5000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));