FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_USE_MOCK=false
ENV VITE_API_BASE_URL=/
RUN npm run test:config \
    && npm run test:events \
    && npm run test:reflection \
    && npm run test:crawl \
    && npm run test:analysis-date \
    && npm run build

FROM python:3.12.4-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    BACKEND_USE_REAL_MODEL=false \
    DEEPSEEK_BASE_URL=https://api.deepseek.com \
    QUICK_THINK_LLM=deepseek-chat \
    DEEP_THINK_LLM=deepseek-reasoner \
    LLM_TIMEOUT=120 \
    LLM_MAX_RETRIES=3 \
    RUNTIME_CONFIG_PATH=/app/Analyst/runtime/server_runtime_config.json \
    ALGORITHM_REGISTRY_PATH=/app/Analyst/runtime/algorithm_registry.json

WORKDIR /app/Analyst

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx curl \
    && rm -rf /var/lib/apt/lists/*

COPY Analyst/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt \
       fastapi uvicorn python-dotenv python-multipart baostock tushare \
       langgraph-prebuilt==1.0.8 \
    && python -m pip install \
       torch==2.12.1 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip check \
    && python -c "from importlib.metadata import version; actual=version('langgraph-prebuilt'); assert actual == '1.0.8', f'expected langgraph-prebuilt 1.0.8, got {actual}'"

COPY Analyst/ ./
RUN python -m compileall \
    api_server.py \
    agent/Reflection.py \
    services/analysis_runner.py \
    services/crawl_date_range.py \
    services/data_fetch_service.py \
    services/eastmoney_data_service.py \
    services/market_data_normalizer.py \
    services/reflection_payload.py \
    services/task_event_stream.py

COPY --from=frontend-builder /build/frontend/dist /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/entrypoint.sh /usr/local/bin/analystverse-entrypoint

RUN chmod +x /usr/local/bin/analystverse-entrypoint \
    && mkdir -p /app/Analyst/result /app/Analyst/runtime /run/nginx

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/analystverse-entrypoint"]
