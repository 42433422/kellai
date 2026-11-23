FROM python:3.12-slim AS base

# 系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker layer cache）
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

# 再拷代码
COPY app/ app/

# 数据目录
RUN mkdir -p /data
ENV KELLAI_DATA_DIR=/data

ENV KELLAI_PORT=8793

EXPOSE 8793

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8793", "--workers", "1"]
