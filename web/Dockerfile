FROM nginx:1.27-alpine
# 설정 파일은 기동 시 환경변수(GATEWAY_UPSTREAM, NGINX_RESOLVER)로 생성한다 (render-nginx-conf.sh 참고)
RUN rm /etc/nginx/conf.d/default.conf
COPY web/render-nginx-conf.sh /docker-entrypoint.d/40-render-nginx-conf.sh
RUN chmod +x /docker-entrypoint.d/40-render-nginx-conf.sh
COPY web/public/ /usr/share/nginx/html/
EXPOSE 80
