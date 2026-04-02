# Build context is ./backend  (same pattern as all other services)
# docker build -f stripe_wrapper/Dockerfile -t stripe-wrapper ./backend

FROM python:3.13-slim

WORKDIR /app

# Install dependencies from the shared requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY stripe_wrapper/ ./stripe_wrapper/

WORKDIR /app/stripe_wrapper

EXPOSE 8004

CMD ["uvicorn", "stripe_wrapper:app", "--host", "0.0.0.0", "--port", "8004"]
