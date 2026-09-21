# 双色球市场分析系统 V1.0
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=7166
ENV TZ=Asia/Shanghai
# 容器启动时按数据时效策略智能判断是否拉取
ENV SSQ_STARTUP_FETCH=auto

EXPOSE 7166

# 单 worker：与工程说明一致
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:7166", "app:app"]
