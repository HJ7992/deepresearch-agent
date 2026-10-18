FROM python:3.12-slim

WORKDIR /app

# 先拷贝依赖清单与源码（hatchling 构建需要 src 与 README）
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data ./data

# 用 uv 装依赖（--frozen 保证与 uv.lock 一致）
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    QDRANT_LOCAL_PATH=/app/.qdrant

EXPOSE 8000

CMD ["uvicorn", "deepresearch.api:app", "--host", "0.0.0.0", "--port", "8000"]
