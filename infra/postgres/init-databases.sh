#!/bin/bash
# 서비스별 DB와 전용 계정을 만든다. 각 계정은 자기 DB에만 접속할 수 있다.
set -e

create_service_db() {
  local db="$1" user="$2" password="$3"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE USER ${user} WITH PASSWORD '${password}';
    CREATE DATABASE ${db} OWNER ${user};
    REVOKE ALL ON DATABASE ${db} FROM PUBLIC;
EOSQL
}

create_service_db auth_db auth_user "$AUTH_DB_PASSWORD"
create_service_db character_db character_user "$CHARACTER_DB_PASSWORD"
create_service_db dungeon_db dungeon_user "$DUNGEON_DB_PASSWORD"
create_service_db quest_db quest_user "$QUEST_DB_PASSWORD"
