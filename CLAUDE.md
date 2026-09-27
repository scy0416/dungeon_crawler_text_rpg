# CLAUDE.md

이 파일은 Claude Code가 이 리포지토리에서 작업할 때 참고하는 프로젝트 가이드입니다.

## 프로젝트 개요

FastAPI 기반 MSA(마이크로서비스 아키텍처) 학습용 프로젝트: 텍스트 기반 던전 크롤러 RPG 백엔드.
자세한 기획/일정은 `기획서_및_계획서.md` 참고.

**핵심 목표**: 실제 서비스 완성도보다 **MSA 패턴 학습**(서비스 분리, API Gateway, 이벤트 기반 통신)이 우선한다. 작업 시 이 우선순위를 항상 고려할 것.

## 아키텍처 원칙 (반드시 준수)

1. **서비스 간 직접 DB 접근 금지**: 각 서비스는 자기 DB에만 접근한다. 다른 서비스의 데이터가 필요하면 HTTP API 호출 또는 이벤트 구독으로 해결한다.
2. **동기 vs 비동기 통신 구분**:
   - 클라이언트 요청에 즉시 응답이 필요하면 → HTTP (httpx)
   - 한 서비스의 상태 변화가 다른 서비스의 상태 변화를 유발하면 → Redis Streams 이벤트
3. **Gateway는 비즈니스 로직을 가지지 않는다**: 라우팅과 (선택적으로) 인증 검증만 수행한다.
4. **이벤트 스키마는 `shared/events.py`에 pydantic 모델로 정의**하고 발행/구독 양쪽에서 이 스키마를 import해서 사용한다. 이벤트 필드를 임의로 바꾸지 말고 스키마부터 수정한다.

## 서비스 구성

| 서비스 | 포트 | 책임 |
|---|---|---|
| gateway | 8000 | 라우팅 전용 |
| auth-service | 8001 | 회원가입/로그인/JWT |
| character-service | 8002 | 캐릭터 스탯/인벤토리, `combat_result` 구독 |
| dungeon-service | 8003 | 전투 로직, `combat_result` 발행 |
| quest-service | 8004 | 퀘스트 진행도, `combat_result`/`level_up` 구독 |
| redis | 6379 | 이벤트 버스 (Streams) |
| postgres | 5432 | 컨테이너 1개, 서비스별 DB/계정 분리 (`auth_db`, `character_db`, `dungeon_db`, `quest_db`) |

각 서비스 디렉토리는 동일한 내부 구조를 따른다: `app/main.py`, `app/models.py`, `app/schemas.py`, `app/routes.py`, 그리고 `pyproject.toml`/`uv.lock`, `alembic/`, `tests/`.
새 서비스를 추가할 때도 이 구조를 그대로 따를 것.

## 확정된 기술 결정

- **패키지 관리**: uv. 서비스마다 독립된 `pyproject.toml` + `uv.lock` (uv workspace 사용 안 함)
- **DB**: 처음부터 PostgreSQL + SQLAlchemy 2.x async(asyncpg). 서비스는 자기 전용 계정으로 자기 DB에만 접속
- **스키마 변경**: 서비스별 Alembic 마이그레이션만 사용. `Base.metadata.create_all` 사용 금지
- **shared 사용**: docker-compose 빌드 컨텍스트는 리포 루트, Dockerfile이 `shared/`를 COPY. `shared/`에는 이벤트 스키마 등 계약만 둔다
- **인증**: Gateway가 auth-service `GET /auth/verify`에 검증을 위임하고, 통과하면 `X-User-Id` 헤더를 붙여 전달한다. 내부 서비스는 JWT를 직접 검증하지 않고 `X-User-Id`만 신뢰한다. JWT 비밀키는 auth-service만 가진다
- **에러 처리**: 각 서비스의 `app/errors.py`에서 `AppError` + 예외 핸들러로 공통 에러 포맷을 만든다 (서비스 간 코드 공유 금지이므로 서비스마다 각자 둔다)
- **테스트 DB**: 단위 테스트는 인메모리 SQLite(aiosqlite)로 `get_session`을 override 한다. 테스트에서만 `create_all` 허용
- **스탯 갱신**: 전투 결과에 따른 스탯 변경은 이벤트 컨슈머 → 내부 함수(`app/progression.py`)로만. 전투 결과를 반영하는 HTTP 엔드포인트를 만들지 않는다. 휴식처럼 플레이어가 직접 하는 행동은 HTTP로 처리한다
- **전투 규칙**: 기획서 4.4.1이 기준. dungeon-service `app/combat.py`는 I/O 없는 순수 로직으로 유지하고 난수는 반드시 세션 시드에서 파생한다

## 개발 명령어

```bash
# 전체 스택 기동
docker-compose up --build

# 특정 서비스만 재빌드 후 기동
docker-compose up --build character-service

# 로그 확인
docker-compose logs -f dungeon-service

# 서비스별 단위 테스트 (예시: character-service)
cd character-service && uv run pytest

# 전체 서비스 테스트 (리포지토리 루트에서)
for d in auth-service character-service dungeon-service quest-service; do
  (cd "$d" && uv run pytest)
done

# 의존성 추가 (예시)
cd character-service && uv add httpx

# 마이그레이션 생성/적용 (예시: character-service 컨테이너)
docker compose exec character-service alembic revision --autogenerate -m "create characters"
docker compose exec character-service alembic upgrade head
```

## 코딩 컨벤션

- Python 3.12, 타입 힌트 필수 (함수 시그니처에 최소한 파라미터/리턴 타입 명시)
- API 요청/응답은 반드시 Pydantic 모델(`schemas.py`)로 정의, dict를 직접 주고받지 않는다
- 비동기 I/O는 `async def` + `httpx.AsyncClient` / `redis.asyncio` 사용 (동기 클라이언트 혼용 금지)
- 커밋 단위는 서비스 단위로 나눈다 (여러 서비스를 한 커밋에 섞지 않기)
- 에러 응답 포맷은 전 서비스 공통: `{"error": {"code": "...", "message": "..."}}`

## 이벤트 작업 시 체크리스트

새 이벤트를 추가하거나 수정할 때 아래를 항상 함께 갱신한다:
1. `shared/events.py`에 Pydantic 스키마 정의/수정
2. 발행 서비스: `redis_client.xadd(Event.stream_key, event.to_fields())` (필드 `data`에 JSON 전체), 구독 쪽은 `Event.from_fields(fields)`
3. 구독 서비스: Consumer Group 이름은 `{service-name}-group` 규칙을 따른다. `event_id`로 멱등 처리(`processed_events` 테이블에 같은 트랜잭션으로 기록)하고, 시작 시 pending 메시지부터 재처리한다
4. `기획서_및_계획서.md`의 "5. 이벤트 설계" 표를 최신 상태로 업데이트

## 하지 말아야 할 것

- 서비스 간 코드 직접 import (예: character-service가 dungeon-service의 모듈을 import) 금지 — 반드시 HTTP/이벤트로 통신
- Gateway에 비즈니스 로직 추가 금지
- 한 PR/커밋에서 여러 서비스의 DB 스키마를 동시에 변경하지 않기 (마이그레이션 추적이 어려워짐)
- 프로덕션 수준의 인증/보안 강화에 과도한 시간 투자 금지 (학습 목적 프로젝트임을 항상 상기)

## 현재 진행 상황 확인 방법

`기획서_및_계획서.md`의 "8. 개발 단계별 계획" 체크리스트를 참고해서 현재 Phase를 파악하고, 해당 Phase의 작업 범위 내에서만 작업할 것. Phase를 건너뛰어 다음 단계 기능을 먼저 구현하지 않는다.
