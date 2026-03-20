FROM python:3.12-slim

WORKDIR /app

# Build context is ./backend — so requirements.txt is backend/requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only this service's source files
COPY inventory/ .

# Generate gRPC stubs from the proto file
# Output lands in /app (same directory as the rest of the source)
RUN python -m grpc_tools.protoc \
    -I./proto \
    --python_out=. \
    --grpc_python_out=. \
    ./proto/inventory.proto

ENV PYTHONUNBUFFERED=1

# 8001 = HTTP/REST   50051 = gRPC
EXPOSE 8001 50051

CMD ["uvicorn", "inventory:app", "--host", "0.0.0.0", "--port", "8001"]
