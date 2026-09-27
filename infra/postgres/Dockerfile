# 서비스별 DB/계정 초기화 스크립트를 포함한 PostgreSQL 이미지.
# 로컬(docker compose)과 ECS가 같은 이미지를 쓴다. 호스트 파일 bind mount에 의존하지 않기 위함.
FROM postgres:16-alpine
COPY init-databases.sh /docker-entrypoint-initdb.d/init-databases.sh
