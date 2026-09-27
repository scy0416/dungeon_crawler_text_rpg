#!/bin/bash
# 서비스별 DB와 전용 계정을 만든다. 각 계정은 자기 DB에만 접속할 수 있다.
#
# 새 볼륨이면 postgres 컨테이너가 처음 뜰 때 자동 실행된다.
# 여러 번 실행해도 안전하므로(이미 있으면 건너뜀) 서비스를 추가한 뒤 기존 볼륨에는 직접 실행한다:
#   docker compose exec postgres bash /docker-entrypoint-initdb.d/init-databases.sh
set -e

create_service_db() {
  local db="$1" user="$2" password="$3"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<EOSQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${user}') THEN
    CREATE ROLE ${user} LOGIN PASSWORD '${password}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${db} OWNER ${user}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${db}')\gexec
REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
EOSQL
}

create_service_db auth_db auth_user "$AUTH_DB_PASSWORD"
create_service_db character_db character_user "$CHARACTER_DB_PASSWORD"
create_service_db dungeon_db dungeon_user "$DUNGEON_DB_PASSWORD"
create_service_db quest_db quest_user "$QUEST_DB_PASSWORD"
create_service_db notification_db notification_user "$NOTIFICATION_DB_PASSWORD"
