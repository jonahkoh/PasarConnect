# Build context is ./backend
# docker build -f claim_log/Dockerfile -t claim-log-service ./backend

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY claim_log/ ./claim_log/

WORKDIR /app/claim_log

EXPOSE 8006

CMD ["uvicorn", "claim_log:app", "--host", "0.0.0.0", "--port", "8006"]
