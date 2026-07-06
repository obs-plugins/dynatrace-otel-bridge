FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PYTHONPATH=/app/src \
    HOST=0.0.0.0 \
    PORT=8080

CMD ["uvicorn", "dify_workflow_otel_exporter.main:app", "--host", "0.0.0.0", "--port", "8080"]
