# Build context is ./backend  (same pattern as inventory and claim)
# docker build -f payment/Dockerfile -t payment-service ./backend

FROM python:3.13-slim

WORKDIR /app

# Install dependencies from the shared requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY payment/ ./payment/
# Copy shared utilities (jwt_auth, etc.)
COPY shared/ ./shared/

WORKDIR /app/payment

# Make the shared/ package importable from /app
ENV PYTHONPATH=/app

# Generate gRPC stubs from the service's own proto copy
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/inventory.proto \
    ./proto/payment_log.proto \
    ./proto/verification.proto

EXPOSE 8003

CMD ["uvicorn", "payment:app", "--host", "0.0.0.0", "--port", "8003"]
