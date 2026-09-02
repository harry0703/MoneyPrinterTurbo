const express = require('express');
const cors = require('cors');
const { PrismaClient } = require('@prisma/client');
const bodyParser = require('express').json;
const jwt = require('jsonwebtoken');
const bcrypt = require('bcryptjs');

require('dotenv').config();
const prisma = new PrismaClient();
const app = express();
app.use(cors());
app.use(bodyParser());

const PORT = process.env.PORT || 4000;
const JWT_SECRET = process.env.JWT_SECRET || 'change-me';
const ADMIN_SECRET = process.env.ADMIN_SECRET || ''; // optional secret to create admin users during registration

// Health
app.get('/health', (req, res) => res.json({ ok: true }));

// Create initial admin if requested via env variables
async function ensureInitialAdmin() {
  const email = process.env.ADMIN_INITIAL_EMAIL;
  const pwd = process.env.ADMIN_INITIAL_PASSWORD;
  if (!email || !pwd) {
    console.log('ADMIN_INITIAL_EMAIL or ADMIN_INITIAL_PASSWORD not set; skipping initial admin creation.');
    return;
  }
  try {
    const count = await prisma.user.count({ where: { role: 'admin' } });
    if (count === 0) {
      const hashed = await bcrypt.hash(pwd, 10);
      const user = await prisma.user.create({ data: { email, password: hashed, name: 'Administrator', role: 'admin' } });
      console.log(`Created initial admin user: ${user.email} (change password after first login)`);
    } else {
      console.log('Admin user already exists; skipping initial admin creation.');
    }
  } catch (e) {
    console.error('Error while creating initial admin:', e.message || e);
  }
}

// Simple auth: register/login
app.post('/auth/register', async (req, res) => {
  const { email, password, name, adminSecret } = req.body;
  if (!email || !password) return res.status(400).json({ error: 'email/password required' });
  const hashed = await bcrypt.hash(password, 10);
  const role = (ADMIN_SECRET && adminSecret === ADMIN_SECRET) ? 'admin' : 'agent';
  try {
    const user = await prisma.user.create({ data: { email, password: hashed, name, role } });
    res.json({ id: user.id, email: user.email, role: user.role });
  } catch (e) {
    res.status(400).json({ error: 'user exists or invalid' });
  }
});

app.post('/auth/login', async (req, res) => {
  const { email, password } = req.body;
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user) return res.status(401).json({ error: 'invalid' });
  const ok = await bcrypt.compare(password, user.password);
  if (!ok) return res.status(401).json({ error: 'invalid' });
  const token = jwt.sign({ sub: user.id, role: user.role }, JWT_SECRET, { expiresIn: '8h' });
  res.json({ token });
});

// Middleware
function auth(req, res, next) {
  const h = req.headers.authorization;
  if (!h) return res.status(401).json({ error: 'no auth' });
  const token = h.replace('Bearer ', '');
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    req.user = payload;
    next();
  } catch (e) { res.status(401).json({ error: 'invalid token' }); }
}

function requireRole(role) {
  return (req, res, next) => {
    if (!req.user) return res.status(401).json({ error: 'no auth' });
    if (req.user.role !== role) return res.status(403).json({ error: 'forbidden' });
    next();
  };
}

// Me endpoint
app.get('/me', auth, async (req, res) => {
  const user = await prisma.user.findUnique({ where: { id: req.user.sub } });
  if (!user) return res.status(404).json({ error: 'not found' });
  res.json({ id: user.id, email: user.email, name: user.name, role: user.role });
});

// Users management (admin)
app.get('/users', auth, requireRole('admin'), async (req, res) => {
  const users = await prisma.user.findMany({ select: { id: true, email: true, name: true, role: true, createdAt: true } });
  res.json(users);
});

app.put('/users/:id/role', auth, requireRole('admin'), async (req, res) => {
  const id = parseInt(req.params.id);
  const { role } = req.body;
  if (!['admin', 'agent'].includes(role)) return res.status(400).json({ error: 'invalid role' });
  const user = await prisma.user.update({ where: { id }, data: { role } });
  res.json({ id: user.id, role: user.role });
});

// Leads routes
app.get('/leads', auth, async (req, res) => {
  const leads = await prisma.lead.findMany({ include: { owner: true } });
  res.json(leads);
});

app.post('/leads', auth, async (req, res) => {
  const data = req.body;
  const lead = await prisma.lead.create({ data: { ...data, ownerId: req.user.sub } });
  res.json(lead);
});

app.get('/leads/:id', auth, async (req, res) => {
  const id = parseInt(req.params.id);
  const lead = await prisma.lead.findUnique({ where: { id } });
  res.json(lead);
});

app.put('/leads/:id', auth, async (req, res) => {
  const id = parseInt(req.params.id);
  const lead = await prisma.lead.update({ where: { id }, data: req.body });
  res.json(lead);
});

// Delete protected to admin
app.delete('/leads/:id', auth, requireRole('admin'), async (req, res) => {
  const id = parseInt(req.params.id);
  await prisma.lead.delete({ where: { id } });
  res.json({ ok: true });
});

// Export leads to CSV (admin only)
app.get('/leads/export', auth, requireRole('admin'), async (req, res) => {
  const leads = await prisma.lead.findMany({ include: { owner: true } });
  const header = ['id','name','business','phone','whatsapp','email','source','stage','notes','owner_email','createdAt','updatedAt'];
  const rows = leads.map(l => [
    l.id,
    escapeCsv(l.name),
    escapeCsv(l.business || ''),
    escapeCsv(l.phone || ''),
    escapeCsv(l.whatsapp || ''),
    escapeCsv(l.email || ''),
    escapeCsv(l.source || ''),
    escapeCsv(l.stage || ''),
    escapeCsv(l.notes || ''),
    l.owner ? l.owner.email : '',
    l.createdAt.toISOString(),
    l.updatedAt.toISOString()
  ]);
  const csv = [header.join(','), ...rows.map(r => r.join(','))].join('\n');
  res.setHeader('Content-Type', 'text/csv');
  res.setHeader('Content-Disposition', 'attachment; filename="leads.csv"');
  res.send(csv);
});

function escapeCsv(v) {
  if (v == null) return '';
  const s = String(v);
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

// Change password (own account)
app.put('/auth/password', auth, async (req, res) => {
  const { currentPassword, newPassword } = req.body;
  if (!currentPassword || !newPassword) return res.status(400).json({ error: 'currentPassword and newPassword required' });
  const user = await prisma.user.findUnique({ where: { id: req.user.sub } });
  if (!user) return res.status(404).json({ error: 'user not found' });
  const ok = await bcrypt.compare(currentPassword, user.password);
  if (!ok) return res.status(401).json({ error: 'invalid current password' });
  const hashed = await bcrypt.hash(newPassword, 10);
  await prisma.user.update({ where: { id: user.id }, data: { password: hashed } });
  res.json({ ok: true });
});

// Admin: change another user's password without current password
app.put('/users/:id/password', auth, requireRole('admin'), async (req, res) => {
  const id = parseInt(req.params.id);
  const { newPassword } = req.body;
  if (!newPassword) return res.status(400).json({ error: 'newPassword required' });
  const hashed = await bcrypt.hash(newPassword, 10);
  await prisma.user.update({ where: { id }, data: { password: hashed } });
  res.json({ ok: true });
});

// WhatsApp send mock endpoint (integrate Twilio/WhatsApp Business API later)
app.post('/send/whatsapp', auth, async (req, res) => {
  const { to, message } = req.body;
  // For now just log and return success; replace with real provider call.
  console.log('WhatsApp send', to, message);
  res.json({ ok: true, provider: 'mock' });
});

// Start server after optional initialization
(async () => {
  await ensureInitialAdmin();
  app.listen(PORT, () => {
    console.log(`Server listening http://localhost:${PORT}`);
  });
})();
