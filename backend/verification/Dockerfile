# Build context is ./backend  (matches all other services)
# docker build -f verification_service/Dockerfile -t verification-service ./backend
FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY verification/ ./verification/

WORKDIR /app/verification

# Generate gRPC stubs from the service's own proto
RUN python -m grpc_tools.protoc \
  -I./proto \
  --python_out=. \
  --grpc_python_out=. \
  ./proto/verification.proto

EXPOSE 8009
EXPOSE 50052

CMD ["uvicorn", "verification:app", "--host", "0.0.0.0", "--port", "8009", "--workers", "1"]
