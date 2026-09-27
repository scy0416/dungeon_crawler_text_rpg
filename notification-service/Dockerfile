# 빌드 컨텍스트: 리포지토리 루트 (shared/ 를 함께 COPY 하기 위해)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1     UV_LINK_MODE=copy     UV_PROJECT_ENVIRONMENT=/opt/venv     PATH="/opt/venv/bin:$PATH"     PYTHONPATH=/app

WORKDIR /app
COPY notification-service/pyproject.toml notification-service/uv.lock ./
RUN uv sync --frozen --no-dev

COPY shared/ ./shared/
COPY notification-service/ ./

EXPOSE 8005
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8005"]
