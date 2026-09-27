#!/bin/sh
# nginx 기동 직전에 실행되어(/docker-entrypoint.d/) 환경변수로 설정 파일을 만든다.
#
#   GATEWAY_UPSTREAM  /api/* 를 넘길 Gateway 주소 (기본: gateway:8000)
#   NGINX_RESOLVER    DNS 서버 주소.
#                     - 지정하면 요청 시점에 Gateway 주소를 다시 찾는다 (컨테이너 재생성으로 IP가 바뀌어도 동작).
#                       로컬 docker compose: 127.0.0.11 (Docker 내장 DNS)
#                       ECS + Cloud Map DNS 서비스 디스커버리: 169.254.169.253 (VPC DNS)
#                     - 비우면 nginx 기동 시 한 번만 찾는다. /etc/hosts도 사용하므로 ECS Service Connect에 맞다.
set -eu

GATEWAY_UPSTREAM="${GATEWAY_UPSTREAM:-gateway:8000}"
NGINX_RESOLVER="${NGINX_RESOLVER:-}"

if [ -n "$NGINX_RESOLVER" ]; then
  # 변수로 proxy_pass 하면 URI를 직접 바꿔야 한다: /api/characters → /characters
  API_PROXY="resolver ${NGINX_RESOLVER} valid=10s ipv6=off;
        set \$gateway http://${GATEWAY_UPSTREAM};
        rewrite ^/api/(.*)\$ /\$1 break;
        proxy_pass \$gateway;"
else
  # 끝의 / 때문에 location 접두사(/api/)가 잘려서 전달된다
  API_PROXY="proxy_pass http://${GATEWAY_UPSTREAM}/;"
fi

cat > /etc/nginx/conf.d/default.conf <<EOF
server {
    listen 80;
    root /usr/share/nginx/html;

    # 로드밸런서/컨테이너 헬스체크
    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok";
    }

    # 웹 클라이언트는 Gateway만 호출한다
    location /api/ {
        ${API_PROXY}
        proxy_set_header Host \$host;
    }

    location / {
        try_files \$uri /index.html;
    }
}
EOF

echo "nginx: /api/ -> http://${GATEWAY_UPSTREAM} (resolver: ${NGINX_RESOLVER:-none, resolve at startup})"
