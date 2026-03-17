# Build context is ./backend
# docker build -f payment_log/Dockerfile -t payment-log-service ./backend

FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY payment_log/ ./payment_log/

WORKDIR /app/payment_log

## Generate gRPC stubs used for orchestrator->state-manager RPC updates
RUN python -m grpc_tools.protoc \
	-I./proto \
	--python_out=. \
	--grpc_python_out=. \
	./proto/payment_log.proto

EXPOSE 8005

CMD ["uvicorn", "payment_log:app", "--host", "0.0.0.0", "--port", "8005"]
