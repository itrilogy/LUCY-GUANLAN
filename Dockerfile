# 双色球市场分析系统 V1.0
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8080
# 容器内默认不自动外网爬取
ENV SSQ_STARTUP_FETCH=false

EXPOSE 8080

# 单 worker：与工程说明一致
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "app:app"]
