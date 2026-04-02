# Build context is ./backend  (same pattern as all other services)
# docker build -f outsystems/Dockerfile -t verification-service ./backend
FROM python:3.13-slim

WORKDIR /app

# Install dependencies from the shared requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY outsystems/ ./outsystems/

WORKDIR /app/outsystems

# Generate gRPC stubs from the service's own proto
RUN python -m grpc_tools.protoc \
  -I./proto \
  --python_out=. \
  --grpc_python_out=. \
  ./proto/verification.proto

EXPOSE 8007
EXPOSE 50052

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]
