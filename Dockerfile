# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# انسخ ملف المتطلبات وثبتها
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# انسخ كل الملفات
COPY . .

EXPOSE 8080

# غيّر "app:app" اذا entrypoint غير كده
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]