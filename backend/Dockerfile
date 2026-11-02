FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates libvulkan1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY assets ./assets
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
RUN useradd -m -u 10001 blink && mkdir -p /data/media && chown -R blink:blink /data/media /app
USER blink
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips","127.0.0.1"]
