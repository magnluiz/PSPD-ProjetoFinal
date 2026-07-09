FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY hospital_pb2.py hospital_pb2_grpc.py server.py ./

ENV GRPC_PORT=50053
ENV METRICS_PORT=9102
EXPOSE 50053 9102

CMD ["python", "server.py"]
