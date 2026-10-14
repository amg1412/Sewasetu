FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /var/sewasetu/uploads /var/log/sewasetu \
    && crontab /app/deploy/crontab

EXPOSE 8000
# threads: a slow phone upload must not pin a whole worker during the month-end rush
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--worker-class", "gthread", "--threads", "8", "--timeout", "60", "app:app"]
