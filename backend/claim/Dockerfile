# Build context is ./backend  (same pattern as inventory)
# docker build -f claim/Dockerfile -t claim-service ./backend

FROM python:3.13-slim

WORKDIR /app

# Install dependencies from the shared requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY claim/ ./claim/
# Copy shared utilities (jwt_auth, etc.)
COPY shared/ ./shared/
WORKDIR /app/claim

# Make the shared/ package importable from /app
ENV PYTHONPATH=/app

# Generate gRPC stubs from the service's own proto copies
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/inventory.proto \
    ./proto/claim_log.proto \
    ./proto/verification.proto
    
EXPOSE 8002

CMD ["uvicorn", "claim:app", "--host", "0.0.0.0", "--port", "8002"]