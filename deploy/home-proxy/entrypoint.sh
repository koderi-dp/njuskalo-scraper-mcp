#!/bin/sh
# Put the credentials from .env into the config (tinyproxy can't read env vars itself).
set -eu
: "${PROXY_USER:?set PROXY_USER in .env}"
: "${PROXY_PASSWORD:?set PROXY_PASSWORD in .env}"
sed "s|__USER__|$PROXY_USER|; s|__PASSWORD__|$PROXY_PASSWORD|" /etc/tinyproxy/tinyproxy.conf > /tmp/tinyproxy.conf
exec tinyproxy -d -c /tmp/tinyproxy.conf
