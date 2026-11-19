FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

COPY docker/requirements-backend.txt /tmp/requirements-backend.txt
RUN pip install --no-cache-dir -r /tmp/requirements-backend.txt

COPY backend /app/backend

EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
