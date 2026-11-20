#!/bin/sh
set -eu

uvicorn api_server:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers 1 &
uvicorn_pid=$!

terminate() {
  kill -TERM "$uvicorn_pid" 2>/dev/null || true
}

trap terminate INT TERM EXIT

nginx -g 'daemon off;' &
nginx_pid=$!

while kill -0 "$uvicorn_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
  sleep 1
done

kill -TERM "$uvicorn_pid" "$nginx_pid" 2>/dev/null || true
wait "$uvicorn_pid" 2>/dev/null || true
wait "$nginx_pid" 2>/dev/null || true
exit 1
