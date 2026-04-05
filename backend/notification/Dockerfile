# Build context is ./backend
# docker build -f notification/Dockerfile -t notification-service ./backend

FROM node:20-alpine

WORKDIR /app

COPY notification/package*.json ./
RUN npm install --omit=dev

COPY notification/notification.js .

EXPOSE 8011

CMD ["node", "notification.js"]
