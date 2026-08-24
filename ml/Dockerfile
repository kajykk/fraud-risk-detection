# ML 评分推理服务镜像（D03 §1.3）
# 基础镜像：nvidia/cuda:12.2-runtime-ubuntu22.04（含 CUDA 12.2）
# 暴露端口：8501（ML Scoring Service，对齐 D03 §2.2）
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

# 非 root 运行（容器安全基线）
RUN groupadd -r frd && useradd -r -g frd -u 10001 frd \
    && chown -R frd:frd /app
USER frd

ENV ML_HOST=0.0.0.0 \
    ML_PORT=8501 \
    ML_WORKERS=4

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://localhost:8501/health || exit 1

CMD ["python", "-m", "uvicorn", "ml.scoring.main:app", \
     "--host", "0.0.0.0", "--port", "8501", "--workers", "4"]
