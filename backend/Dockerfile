FROM node:18-alpine
WORKDIR /usr/src/app
COPY package.json package-lock.json* ./
RUN npm install --production
COPY . .
RUN npx prisma generate || true
EXPOSE 4000
CMD ["node", "src/index.js"]
