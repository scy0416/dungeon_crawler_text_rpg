#!/usr/bin/env bash
# 배포용 이미지를 빌드하고 레지스트리 이름으로 태그한다 (예: Amazon ECR).
#
#   REGISTRY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com ./scripts/build-images.sh          # 빌드만
#   REGISTRY=123456789012.dkr.ecr.ap-northeast-2.amazonaws.com ./scripts/build-images.sh --push   # 빌드 + push
#
# 환경변수
#   REGISTRY  레지스트리 주소 (기본: local → 로컬 태그만)
#   PREFIX    저장소 이름 접두사 (기본: dungeon-crawler/ → ECR 저장소 "dungeon-crawler/gateway" 등)
#   TAG       이미지 태그 (기본: 현재 git 커밋 짧은 해시)
#   PLATFORM  대상 플랫폼 (기본: linux/amd64 = Fargate X86_64. ARM64 Fargate면 linux/arm64)
#
# redis는 공식 이미지(redis:7-alpine)를 그대로 쓰므로 여기서 빌드하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

REGISTRY="${REGISTRY:-local}"
PREFIX="${PREFIX:-dungeon-crawler/}"
TAG="${TAG:-$(git rev-parse --short HEAD)}"
PLATFORM="${PLATFORM:-linux/amd64}"
PUSH=false
if [[ "${1:-}" == "--push" ]]; then
  PUSH=true
fi

# 이름:Dockerfile:빌드 컨텍스트 (서비스들은 shared/ 를 포함하려고 리포 루트가 컨텍스트)
IMAGES=(
  "web:web/Dockerfile:."
  "gateway:gateway/Dockerfile:."
  "auth-service:auth-service/Dockerfile:."
  "character-service:character-service/Dockerfile:."
  "dungeon-service:dungeon-service/Dockerfile:."
  "quest-service:quest-service/Dockerfile:."
  "notification-service:notification-service/Dockerfile:."
  "postgres:infra/postgres/Dockerfile:infra/postgres"
)

for entry in "${IMAGES[@]}"; do
  IFS=: read -r name dockerfile context <<<"$entry"
  image="${REGISTRY}/${PREFIX}${name}:${TAG}"
  echo "==> ${image}"
  docker build --platform "$PLATFORM" -f "$dockerfile" -t "$image" "$context"
  if $PUSH; then
    docker push "$image"
  fi
done

echo "done: ${#IMAGES[@]} images tagged ${TAG} (platform ${PLATFORM}, push=${PUSH})"
