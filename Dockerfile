FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data && chown -R 10001:10001 /app
USER 10001
EXPOSE 10000
CMD ["sh", "-c", "python -c 'from app import app, db; ctx = app.app_context(); ctx.push(); db.create_all(); ctx.pop()' && exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 90 app:app"]
