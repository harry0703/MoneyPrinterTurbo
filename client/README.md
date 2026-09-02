Telemarketing client (React + Vite)

Run (from repo root):
cd client
npm install
npm run dev

Notes:
- The client expects backend at http://localhost:4000. Change VITE_API_BASE env var to point elsewhere.
- Use the UI to register/login, add leads and click 'Enviar WhatsApp' (mock). Replace backend /send/whatsapp with Twilio/WhatsApp provider later.

Admin user creation via UI:
- Set ADMIN_SECRET in backend/.env (e.g., ADMIN_SECRET=mi_clave_segura).
- In the client registration form, fill the field "Admin secret (opcional, para crear admin)" with the same value to create an admin account.
- If ADMIN_SECRET is empty or incorrect, newly registered accounts will have role 'agent' by default.

CLI alternative to create admin:
- curl -X POST http://localhost:4000/auth/register -H "Content-Type: application/json" -d '{"email":"admin@local","password":"secret","name":"Admin","adminSecret":"mi_clave_segura"}'
