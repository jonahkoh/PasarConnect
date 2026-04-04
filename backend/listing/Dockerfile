# Build context is ./backend
# docker build -f listing/Dockerfile -t listing-service ./backend

FROM python:3.13-slim

WORKDIR /app

# Install dependencies from the shared requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY listing/ ./listing/

WORKDIR /app/listing

# Generate gRPC stubs from the service's own proto copy
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/inventory.proto

EXPOSE 8008

CMD ["uvicorn", "listing:app", "--host", "0.0.0.0", "--port", "8008"]
