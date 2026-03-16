# Build context is ./backend
# docker build -f claim_log/Dockerfile -t claim-log-service ./backend

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY claim_log/ ./claim_log/

WORKDIR /app/claim_log

# Generate gRPC stubs used to synchronize inventory state on status updates
RUN python -m grpc_tools.protoc \
	-I./proto \
	--python_out=. \
	--grpc_python_out=. \
	./proto/inventory.proto \
	./proto/claim_log.proto

EXPOSE 8006

CMD ["uvicorn", "claim_log:app", "--host", "0.0.0.0", "--port", "8006"]
