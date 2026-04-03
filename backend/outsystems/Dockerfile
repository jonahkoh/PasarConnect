# Build context is ./backend
# docker build -f outsystems/Dockerfile -t outsystems-service ./backend
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY outsystems/ ./outsystems/
COPY shared/ ./shared/

WORKDIR /app/outsystems

EXPOSE 8007

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
