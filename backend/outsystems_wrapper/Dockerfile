# Build context is ./backend
# docker build -f outsystems/Dockerfile -t outsystems-service ./backend
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY outsystems_wrapper/ ./outsystems_wrapper/
COPY shared/ ./shared/

WORKDIR /app/outsystems_wrapper

# Generate gRPC stubs for calling the verification service
RUN python -m grpc_tools.protoc \
  -I./proto \
  --python_out=. \
  --grpc_python_out=. \
  ./proto/verification.proto

EXPOSE 8007

CMD ["uvicorn", "outsystems_wrapper:app", "--host", "0.0.0.0", "--port", "8007"]
