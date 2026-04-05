# Build context is ./backend  (same pattern as other services)
# docker build -f waitlist/Dockerfile -t waitlist-service ./backend

FROM python:3.13-slim

WORKDIR /app

# Install dependencies from the shared requirements file
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy service source
COPY waitlist/ ./waitlist/

WORKDIR /app/waitlist

# Generate gRPC stubs from the proto file
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/waitlist.proto

# Make the shared/ package importable from /app
ENV PYTHONPATH=/app

# 8010 = HTTP/REST   50053 = gRPC
EXPOSE 8010 50053
CMD ["uvicorn", "waitlist:app", "--host", "0.0.0.0", "--port", "8010"]
