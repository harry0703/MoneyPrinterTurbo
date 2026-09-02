Backend (Express + Prisma)

Quick start:
1. Copy backend/.env.example to backend/.env and fill values.
2. From repo root run: docker-compose up --build
3. Generate Prisma client (inside container or locally): npx prisma generate
4. Run migrations (example): npx prisma migrate dev --name init

Notes:
- Database default in docker-compose is Postgres. To use MySQL, change prisma schema provider and DATABASE_URL accordingly.
- Integrations: WhatsApp endpoint is a mock; replace with Twilio or WhatsApp Business API in src/index.js /send/whatsapp.
