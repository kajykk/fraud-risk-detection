# GNN 服务镜像（D03 §4.4）
# 基础镜像：nvidia/cuda:12.2-runtime-ubuntu22.04（含 CUDA 12.2）
# 暴露端口：8502（GNN Service，对齐 D03 §2.2）
# 健康检查：/health

FROM nvidia/cuda:12.2-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 系统依赖 + Python 3.12
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-distutils python3.12-dev \
        python3-pip curl ca-certificates \
        libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip==24.2 \
    && pip install -r /app/requirements.txt

COPY . /app

ENV GNN_HOST=0.0.0.0 \
    GNN_PORT=8502 \
    GNN_WORKERS=2

EXPOSE 8502

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8502/health || exit 1

CMD ["python", "-m", "uvicorn", "gnn.main:app", \
     "--host", "0.0.0.0", "--port", "8502", "--workers", "2"]
