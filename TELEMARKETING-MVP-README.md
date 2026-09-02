Plataforma Telemarketing — MVP

Resumen
- Stack recomendado: Node.js (Express) + React (frontend).
- Canales prioritarios: WhatsApp y Redes sociales (Instagram/Facebook/LinkedIn).
- Objetivo: herramienta para prospectar, contactar, presentar oferta, gestionar objeciones y cerrar ventas; con CRM básico y panel de ventas.

MVP — Funcionalidades clave
1. Prospección automatizada (importar listas, búsquedas básicas, guardar leads).
2. Contacto y mensajería: integración WhatsApp Business API (o Twilio) + plantillas para redes.
3. CRM: contactos, etiquetas, pipeline (etapas: Prospecto, Contactado, Interesado, Negociación, Cerrado).
4. Conversaciones: historial, asignación de agente, notas.
5. Panel de ventas: métricas básicas y export CSV.
6. Gestión de usuarios y roles (admin/agente).

Descargar el proyecto (pasos rápidos)
1. Clonar el repositorio:
   git clone https://github.com/harry0703/MoneyPrinterTurbo.git
   cd MoneyPrinterTurbo
   git checkout reduno3-plataforma-telemarketing

2. Recomendado: usar Node 18+. Instalar dependencias (backend y frontend cuando existan):
   # Backend (en /server o raíz si corresponde)
   npm install

   # Frontend (en /client)
   cd client
   npm install

Entorno y variables (.env)
- Crear un archivo .env en backend con al menos:
  PORT=3000
  NODE_ENV=development
  DATABASE_URL=postgres://user:pass@localhost:5432/telemarketing_db     # o cadena MySQL
  JWT_SECRET=tu_secreto
  WHATSAPP_API_URL=...
  WHATSAPP_API_TOKEN=...

Bases de datos — opciones
A) PostgreSQL (ejemplo rápido)
- Crear base y usuario:
  sudo -u postgres psql
  CREATE USER teleuser WITH ENCRYPTED PASSWORD 'telepass';
  CREATE DATABASE telemarketing_db OWNER teleuser;
  \q

- En .env usar: DATABASE_URL=postgres://teleuser:telepass@localhost:5432/telemarketing_db

B) MySQL (ejemplo rápido)
- Crear base y usuario:
  mysql -u root -p
  CREATE DATABASE telemarketing_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
  CREATE USER 'teleuser'@'localhost' IDENTIFIED BY 'telepass';
  GRANT ALL PRIVILEGES ON telemarketing_db.* TO 'teleuser'@'localhost';
  FLUSH PRIVILEGES;
  EXIT;

- En .env usar: DATABASE_URL=mysql://teleuser:telepass@localhost:3306/telemarketing_db

Docker (opcional) — docker-compose (recomendado)
- Se ha creado un archivo de compose específico para el scaffold: docker-compose.telemarketing.yml
- Uso recomendado (desde la raíz del repo):
  docker compose -f docker-compose.telemarketing.yml up --build -d

Este compose levanta 3 servicios:
- telemarketing_db: Postgres (puerto 5432)
- telemarketing_app: backend Express (puerto 4000)
- telemarketing_client: frontend Vite (puerto 5173)

Ejecutar migraciones Prisma después de levantar los servicios:
  docker compose -f docker-compose.telemarketing.yml exec -T telemarketing_app npx prisma migrate deploy

Si prefieres usar los archivos compose del proyecto original, no los sobreescribe; este archivo nuevo es independiente y específico para el MVP.

Migraciones y ORM
- Elegir ORM (Sequelize, TypeORM, Prisma). Para novatos Prisma o Sequelize son buenas opciones.
- Comandos típicos (ejemplo Prisma):
  npx prisma migrate dev --name init

Arrancar la aplicación (desarrollo)
- Backend:
  npm run dev          # o npm start según scaffold
- Frontend (client):
  cd client
  npm run start

Despliegue en servidor personalizado
1. Subir código al servidor (git pull o rsync).
2. Instalar Node.js y dependencias.
3. Configurar la base de datos (MySQL o Postgres) en el servidor.
4. Ejecutar migraciones.
5. Configurar un proceso PM2 o systemd para mantener la app en producción.
6. (Opcional) Usar Nginx como proxy inverso y SSL (Let's Encrypt).

Siguientes pasos (implementación que voy a crear ahora si confirmas)
- Scaffold minimal: backend Express con endpoints para leads, contactos, pipeline, auth JWT.
- Frontend React con panel básico para crear/editar leads y ver pipeline.
- Integración inicial con WhatsApp vía Twilio (mock si no hay credenciales).
- Docker Compose para la app + DB, y scripts de inicialización.

Si confirmas, comienzo creando la estructura inicial del backend y README de instalación detallada. Para crear archivos en el repo ya se renombró la rama a: reduno3-plataforma-telemarketing

Contacto
Si necesitas que use PostgreSQL o MySQL por defecto en el scaffold indícalo; por defecto usaré PostgreSQL pero dejaré instrucciones para MySQL.
