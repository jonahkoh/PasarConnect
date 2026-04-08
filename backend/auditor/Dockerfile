# Build context is ./backend
# docker build -f auditor/Dockerfile -t auditor-service ./backend

FROM node:20-alpine

WORKDIR /app

COPY auditor/package*.json ./
RUN npm install --omit=dev

COPY auditor/auditor.js .

CMD ["node", "auditor.js"]
