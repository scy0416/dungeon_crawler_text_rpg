# 빌드 컨텍스트: 리포지토리 루트 (shared/ 를 함께 COPY 하기 위해)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1     UV_LINK_MODE=copy     UV_PROJECT_ENVIRONMENT=/opt/venv     PATH="/opt/venv/bin:$PATH"     PYTHONPATH=/app

WORKDIR /app
COPY character-service/pyproject.toml character-service/uv.lock ./
RUN uv sync --frozen --no-dev

COPY shared/ ./shared/
COPY character-service/ ./

EXPOSE 8002
# DB가 아직 준비되지 않았으면 마이그레이션을 재시도한다 (ECS에는 서비스 간 기동 순서가 없다).
# exec로 uvicorn을 PID 1로 띄워야 컨테이너 종료 시 SIGTERM을 받아 정상 종료한다.
CMD ["sh", "-c", "n=0; until alembic upgrade head; do n=$((n+1)); if [ $n -ge 20 ]; then echo 'migration failed' >&2; exit 1; fi; echo 'migration failed, retrying in 3s' >&2; sleep 3; done; exec uvicorn app.main:app --host 0.0.0.0 --port 8002"]
