# ECS(Fargate) 배포 명세

Terraform 등으로 ECS 인프라를 작성할 때 옮겨 적기만 하면 되도록 정리한 명세입니다.
전제: **docker compose의 컨테이너 구성을 그대로 유지**합니다. PostgreSQL과 Redis도 관리형 서비스(RDS/ElastiCache)로 바꾸지 않고 Fargate 컨테이너로 올립니다.

## 1. 전체 구성

```
인터넷 ──▶ ALB :80 ──▶ web (nginx) ──/api/*──▶ gateway ──▶ auth / character / dungeon / quest / notification
                                                              │
                                     postgres (EFS) ◀─────────┤
                                     redis          ◀─────────┘   (Service Connect 네임스페이스 안에서 이름으로 통신)
```

- 외부에 노출하는 것은 **ALB → web 하나**입니다. 웹 클라이언트는 `/api/*`만 호출하고 nginx가 Gateway로 넘깁니다.
- 컨테이너 9개는 각각 **별도 ECS Service**로 만듭니다 (서비스별 독립 배포·확장).
- 서비스 간 주소는 compose와 같은 이름(`gateway`, `postgres`, `redis`, `auth-service` …)을 **ECS Service Connect**의 client alias로 맞춥니다. 그러면 애플리케이션 환경변수 값을 compose와 똑같이 쓸 수 있습니다.

## 2. 이미지

ECR 저장소 이름은 `dungeon-crawler/<이름>`을 기준으로 합니다 (빌드 스크립트 기본값).

| 이름 | Dockerfile | 빌드 컨텍스트 | 비고 |
|---|---|---|---|
| web | `web/Dockerfile` | 리포 루트 | nginx, 설정은 기동 시 환경변수로 생성 |
| gateway | `gateway/Dockerfile` | 리포 루트 | |
| auth-service | `auth-service/Dockerfile` | 리포 루트 | |
| character-service | `character-service/Dockerfile` | 리포 루트 | |
| dungeon-service | `dungeon-service/Dockerfile` | 리포 루트 | |
| quest-service | `quest-service/Dockerfile` | 리포 루트 | |
| notification-service | `notification-service/Dockerfile` | 리포 루트 | |
| postgres | `infra/postgres/Dockerfile` | `infra/postgres` | 서비스별 DB/계정 초기화 스크립트 포함 |
| redis | (빌드 안 함) | | 공식 `redis:7-alpine`. Docker Hub pull 제한이 걱정되면 ECR로 복사 |

서비스 이미지는 `shared/`를 포함해야 해서 빌드 컨텍스트가 **리포 루트**입니다.

```bash
aws ecr get-login-password --region ap-northeast-2 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.ap-northeast-2.amazonaws.com
```

```bash
REGISTRY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com TAG=v1 ./scripts/build-images.sh --push
```

기본 플랫폼은 `linux/amd64`(Fargate X86_64)입니다. ARM64 Fargate를 쓰면 `PLATFORM=linux/arm64`.

## 3. 서비스별 명세

| ECS 서비스 | 컨테이너 포트 | Service Connect 이름(client alias) | desired count | 확장 가능 | 권장 CPU/메모리 |
|---|---|---|---|---|---|
| web | 80 | (클라이언트만, ALB 대상) | 1 | O | 256 / 512 |
| gateway | 8000 | `gateway:8000` | 1 | O | 256 / 512 |
| auth-service | 8001 | `auth-service:8001` | 1 | O | 256 / 512 |
| character-service | 8002 | `character-service:8002` | 1 | O (컨슈머) | 256 / 512 |
| dungeon-service | 8003 | `dungeon-service:8003` | 1 | O (전투 세션은 Redis) | 256 / 512 |
| quest-service | 8004 | `quest-service:8004` | 1 | O (컨슈머) | 256 / 512 |
| notification-service | 8005 | `notification-service:8005` | 1 | O (컨슈머) | 256 / 512 |
| postgres | 5432 | `postgres:5432` | **1 고정** | X | 512 / 1024 |
| redis | 6379 | `redis:6379` | **1 고정** | X | 256 / 512 |

- 컨슈머 서비스는 컨테이너 hostname을 컨슈머 이름으로 씁니다. Fargate 태스크마다 hostname이 달라서 **desired count를 늘려도 그대로 동작**합니다. 죽은 태스크의 pending 메시지는 다른 태스크가 XAUTOCLAIM으로 회수합니다.
- 여러 태스크가 동시에 기동해도 Alembic 마이그레이션은 Postgres advisory lock으로 하나씩만 실행됩니다.
- postgres/redis는 상태를 가진 단일 인스턴스라 **반드시 1개**로 둡니다 (배포 설정: `maximumPercent=100`, `minimumHealthyPercent=0`으로 두 태스크가 동시에 같은 EFS 데이터를 열지 않게).

## 4. 환경변수와 비밀값

비밀값은 Secrets Manager(또는 SSM Parameter Store SecureString)에 두고 Task Definition의 `secrets`로 주입합니다.

### postgres
| 이름 | 종류 | 값 |
|---|---|---|
| `POSTGRES_USER` | env | `postgres` |
| `POSTGRES_PASSWORD` | **secret** | 슈퍼유저 비밀번호 |
| `AUTH_DB_PASSWORD` / `CHARACTER_DB_PASSWORD` / `DUNGEON_DB_PASSWORD` / `QUEST_DB_PASSWORD` / `NOTIFICATION_DB_PASSWORD` | **secret** | 서비스별 DB 계정 비밀번호 (최초 기동 시 계정 생성에 사용) |
| `PGDATA` | env | `/var/lib/postgresql/data/pgdata` (EFS 루트의 `lost+found` 등과 섞이지 않게 하위 폴더 사용) |

### 애플리케이션 서비스
| 서비스 | 이름 | 종류 | 값 |
|---|---|---|---|
| web | `GATEWAY_UPSTREAM` | env | `gateway:8000` |
| web | `NGINX_RESOLVER` | env | **비움** (Service Connect 이름은 기동 시 한 번 해석. 아래 5번 참고) |
| gateway | `AUTH_SERVICE_URL` 외 4개 | env | `http://auth-service:8001`, `http://character-service:8002`, `http://dungeon-service:8003`, `http://quest-service:8004`, `http://notification-service:8005` |
| auth-service | `DATABASE_URL` | **secret** | `postgresql+asyncpg://auth_user:<비번>@postgres:5432/auth_db` |
| auth-service | `JWT_SECRET` | **secret** | 충분히 긴 임의 문자열. **빠뜨리면 개발용 기본값으로 뜨고 경고 로그가 남는다** |
| character-service | `DATABASE_URL` | **secret** | `postgresql+asyncpg://character_user:<비번>@postgres:5432/character_db` |
| character-service | `REDIS_URL` | env | `redis://redis:6379/0` |
| dungeon-service | `DATABASE_URL` | **secret** | `postgresql+asyncpg://dungeon_user:<비번>@postgres:5432/dungeon_db` |
| dungeon-service | `REDIS_URL`, `CHARACTER_SERVICE_URL` | env | `redis://redis:6379/0`, `http://character-service:8002` |
| quest-service | `DATABASE_URL` | **secret** | `postgresql+asyncpg://quest_user:<비번>@postgres:5432/quest_db` |
| quest-service | `REDIS_URL`, `CHARACTER_SERVICE_URL` | env | `redis://redis:6379/0`, `http://character-service:8002` |
| notification-service | `DATABASE_URL` | **secret** | `postgresql+asyncpg://notification_user:<비번>@postgres:5432/notification_db` |
| notification-service | `REDIS_URL`, `CHARACTER_SERVICE_URL` | env | `redis://redis:6379/0`, `http://character-service:8002` |

`CONSUMER_NAME`은 설정하지 않습니다 (hostname 사용).

## 5. 네트워크

- **Service Connect 네임스페이스** 하나(예: `dungeon-crawler`)에 9개 서비스를 모두 넣습니다.
  - postgres, redis, gateway, 5개 서비스: *client-server* 모드. `portMappings`에 이름을 붙이고, `clientAliases`의 `dnsName`을 위 표의 이름과 **정확히 같게** 설정합니다.
  - web: *client* 모드 (다른 서비스를 호출만 함).
- **web의 nginx**: Service Connect 이름은 VPC DNS에는 없고 태스크 안에서만 해석됩니다. 그래서 `NGINX_RESOLVER`를 **비워서** nginx가 기동 시 시스템 해석(`/etc/hosts` 포함)으로 한 번 찾게 합니다.
  - Service Connect 대신 Cloud Map **DNS** 서비스 디스커버리를 쓴다면: `GATEWAY_UPSTREAM=gateway.<네임스페이스>:8000`, `NGINX_RESOLVER=169.254.169.253`(VPC DNS).
- **ALB**: 리스너 80 → web 대상 그룹(포트 80, 대상 유형 `ip`, 헬스체크 `/healthz`).
- **보안 그룹**
  - ALB: 인바운드 80 from 인터넷
  - web: 인바운드 80 from ALB SG
  - 나머지 서비스: 인바운드 각 포트 from 서비스 공용 SG (같은 SG끼리 허용)
  - EFS: 인바운드 2049 from postgres(와 redis) 태스크 SG
- 서브넷: 태스크는 프라이빗 서브넷 + NAT(ECR/Docker Hub pull, CloudWatch 전송용) 또는 퍼블릭 서브넷 + `assignPublicIp=ENABLED`(학습용으로 저렴).

## 6. 헬스체크 (Task Definition `healthCheck`)

Dockerfile의 HEALTHCHECK는 ECS가 쓰지 않으므로 Task Definition에 직접 적습니다.

| 컨테이너 | command |
|---|---|
| web | `["CMD-SHELL", "wget -qO- http://localhost/healthz || exit 1"]` |
| gateway 및 5개 서비스 | `["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:<포트>/health', timeout=3)\" || exit 1"]` |
| postgres | `["CMD-SHELL", "pg_isready -U postgres || exit 1"]` |
| redis | `["CMD-SHELL", "redis-cli ping || exit 1"]` |

서비스 이미지에는 curl이 없어서 python으로 확인합니다. DB 서비스는 기동 시 마이그레이션(최대 약 60초 재시도)을 하므로 `startPeriod`를 60~90초로 둡니다.

## 7. 볼륨

| 대상 | 볼륨 | 설정 |
|---|---|---|
| postgres | EFS | 마운트 경로 `/var/lib/postgresql/data`. Access Point의 POSIX 사용자 **uid/gid 70**(postgres:16-alpine의 postgres 사용자), 루트 디렉터리 권한 0700. 전송 중 암호화 사용 |
| redis | (선택) EFS | 기본은 볼륨 없음 → 태스크 재시작 시 스트림의 미처리 이벤트와 전투 세션이 사라짐. 보존하려면 `/data`에 EFS를 붙이고 command를 `["redis-server", "--appendonly", "yes"]`로 |

## 8. 기동 순서와 동작

- ECS에는 서비스 간 `depends_on`이 없습니다. 모든 서비스를 동시에 만들어도 됩니다.
  - DB 서비스: postgres가 준비될 때까지 마이그레이션을 3초 간격으로 최대 20회 재시도 → 그래도 실패하면 종료 → ECS가 태스크를 다시 띄움
  - 컨슈머: Redis 연결 실패 시 1초 후 재시도
  - web: 기동 시 `gateway` 이름을 찾지 못하면 nginx가 종료 → ECS가 재시작
- 컨테이너 종료: uvicorn이 PID 1이라 SIGTERM을 받으면 바로 정상 종료합니다 (`stopTimeout` 기본값으로 충분).
- 로그: 모든 서비스가 JSON 한 줄 로그를 stdout으로 냅니다 → `awslogs` 드라이버로 CloudWatch Logs에 보내면 `correlation_id`로 검색할 수 있습니다.

## 9. Terraform 리소스 체크리스트

- [ ] VPC, 서브넷, (NAT), 보안 그룹
- [ ] ECR 저장소 8개 (`dungeon-crawler/*`)
- [ ] Secrets Manager 비밀값: postgres 슈퍼유저 비번, 서비스별 DB 비번 5개, 서비스별 `DATABASE_URL` 5개, `JWT_SECRET`
- [ ] EFS 파일시스템 + 마운트 타깃 + Access Point(uid/gid 70)
- [ ] ECS 클러스터 + Service Connect 네임스페이스(Cloud Map HTTP 네임스페이스)
- [ ] IAM: 태스크 실행 역할(ECR pull, 로그, 비밀값 읽기), EFS 사용 시 태스크 역할 권한
- [ ] CloudWatch 로그 그룹 (서비스별)
- [ ] Task Definition 9개 (4·6·7번 반영) + ECS Service 9개 (3·5번 반영)
- [ ] ALB + 대상 그룹(web) + 리스너
- [ ] 비용 정리: 학습이 끝나면 `terraform destroy` (ALB, NAT, EFS는 켜두는 동안 과금)
