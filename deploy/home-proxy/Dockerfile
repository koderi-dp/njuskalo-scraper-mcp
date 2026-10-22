FROM alpine:3.20
RUN apk add --no-cache tinyproxy
COPY tinyproxy.conf filter entrypoint.sh /etc/tinyproxy/
RUN chmod +x /etc/tinyproxy/entrypoint.sh
EXPOSE 8888
ENTRYPOINT ["/etc/tinyproxy/entrypoint.sh"]
