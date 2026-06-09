# =============================================================================
# Rivalens — 竞品分析系统 Docker 镜像
# =============================================================================
# 用法:
#   docker compose up -d                        # 全栈启动
#   docker build -t rivalens .                  # 仅构建
#   docker run --env-file .env rivalens          # 仅 API 服务
# =============================================================================

# ── Stage 1: 浏览器依赖 ─────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS browser-deps

RUN apt-get update && apt-get install -y --no-install-recommends \
    gnupg wget ca-certificates curl \
    && ARCH=$(dpkg --print-architecture) \
    && wget -qO - https://dl.google.com/linux/linux_signing_key.pub | \
       gpg --dearmor -o /etc/apt/trusted.gpg.d/google-chrome.gpg \
    && echo "deb [arch=${ARCH}] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       chromium chromium-driver firefox-esr \
    && rm -rf /var/lib/apt/lists/*

# ── Stage 2: Python 依赖 ────────────────────────────────────────────
FROM browser-deps AS python-deps

ENV PIP_ROOT_USER_ACTION=ignore
WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
       -i https://mirrors.aliyun.com/pypi/simple/ \
       --trusted-host mirrors.aliyun.com

# ── Stage 3: 应用镜像 ───────────────────────────────────────────────
FROM python-deps AS rivalens

WORKDIR /usr/src/app

# 复制应用代码
COPY . .

# 创建非 root 用户并设置目录权限
RUN useradd -m -s /bin/bash rivalens \
    && mkdir -p /usr/src/app/outputs /usr/src/app/logs /usr/src/app/my-docs \
    && chown -R rivalens:rivalens /usr/src/app

USER rivalens

EXPOSE 8000

# 默认启动 API 服务；Celery Worker 通过 docker-compose command 覆盖
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
