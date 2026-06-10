FROM python:3.11-slim AS base

# 系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker layer cache）
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# 再拷代码
COPY app/ app/

# 数据目录
RUN mkdir -p /data
ENV KELLAI_DATA_DIR=/data

# 生产环境必须设置的环境变量（运行时注入）
ENV KELLAI_APP_ENV=production
ENV KELLAI_STRICT_AUTH=1
ENV KELLAI_PORT=8790

EXPOSE 8790

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8790", "--workers", "2"]
