#!/usr/bin/env bash
# Prove the in-cluster build/serve pipeline works before deploying it:
#  - the MkDocs image can build as UID 101 onto a shared volume
#  - nginx-unprivileged (UID 101) can read what it wrote
#  - the symlink swap publishes atomically
#  - a failing --strict build leaves the previous site serving
#
# Docker note: squidfunk/mkdocs-material declares ENTRYPOINT ["mkdocs"]
# (actually `/sbin/tini -- mkdocs`), so every invocation that needs a shell
# in that image passes --entrypoint sh and gives the shell script as the
# command, rather than relying on `sh -c "..."` being appended to the
# entrypoint. This is a Docker-only wrinkle: Kubernetes' `command:
# ["/bin/sh","-c"]` overrides the entrypoint properly and needs no such fix.
#
# Usage: ./pipeline-test.sh /path/to/home-docs
set -euo pipefail

SRC="${1:?usage: pipeline-test.sh /path/to/home-docs}"
MK=squidfunk/mkdocs-material:9.7.7
NG=nginxinc/nginx-unprivileged:1.31.3-alpine
VOL=home-docs-test
NET=home-docs-test-net

NGINX_CONF=""
BROKEN_DIR=""
cleanup() {
  docker rm -f home-docs-web >/dev/null 2>&1 || true
  docker volume rm -f "$VOL" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  [ -z "$NGINX_CONF" ] || rm -f "$NGINX_CONF"
  [ -z "$BROKEN_DIR" ] || rm -rf "$BROKEN_DIR"
}
trap cleanup EXIT
cleanup

docker volume create "$VOL" >/dev/null
docker network create "$NET" >/dev/null

# The shared volume (an emptyDir in Kubernetes) is created root:root 0755 by
# default, so UID 101 cannot create anything under it. In the cluster this
# is what a pod-level `securityContext.fsGroup: 101` fixes automatically for
# every container sharing the volume; Docker has no fsGroup equivalent, so
# this one-shot root container reproduces the same effect by hand before any
# UID-101 container touches the volume.
echo "== prep shared volume (stand-in for fsGroup: 101) =="
docker run --rm --entrypoint sh -v "$VOL":/srv "$MK" \
  -c 'mkdir -p /srv/builds && chown -R 101:101 /srv'

build() {
  local sha="$1" src="$2"
  docker run --rm -u 101:101 -e HOME=/tmp \
    -v "$src":/repo:ro -v "$VOL":/srv --entrypoint sh "$MK" -c \
    "mkdocs build -f /repo/mkdocs.yml -d /srv/builds/$sha --strict \
           && ln -sfn /srv/builds/$sha /srv/current"
}

current_target() {
  docker run --rm --entrypoint readlink -v "$VOL":/srv "$MK" /srv/current
}

echo "== build 1 as UID 101 =="
build aaaaaaa "$SRC"
target=$(current_target)
[ "$target" = "/srv/builds/aaaaaaa" ] || { echo "FAIL: symlink is $target after first build"; exit 1; }
echo "PASS: build 1 wrote /srv/builds/aaaaaaa as UID 101 and symlink points at it"

NGINX_CONF=$(mktemp)
chmod 644 "$NGINX_CONF"  # mktemp defaults to 0600; nginx runs as UID 101, not root
cat > "$NGINX_CONF" <<'EOF'
server {
  listen 8080;
  server_name _;
  root /srv/current;
  index index.html;
  disable_symlinks off;
  location = /healthz { access_log off; return 200 "ok\n"; }
  location / { try_files $uri $uri/ =404; }
}
EOF

docker run -d --name home-docs-web --network "$NET" -p 18080:8080 \
  -v "$VOL":/srv:ro \
  -v "$NGINX_CONF":/etc/nginx/conf.d/default.conf:ro \
  "$NG" >/dev/null
sleep 2

echo "== nginx (UID 101) can read what MkDocs (UID 101) wrote =="
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/)
[ "$code" = "200" ] || { echo "FAIL: got HTTP $code from /"; docker logs home-docs-web; exit 1; }
curl -s http://127.0.0.1:18080/healthz | grep -q ok || { echo "FAIL: healthz"; exit 1; }
echo "PASS: served HTTP 200"

echo "== symlink swap publishes a new build =="
build bbbbbbb "$SRC"
target=$(current_target)
[ "$target" = "/srv/builds/bbbbbbb" ] || { echo "FAIL: symlink is $target"; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/)
[ "$code" = "200" ] || { echo "FAIL: HTTP $code after swap"; exit 1; }
body=$(curl -s http://127.0.0.1:18080/)
echo "$body" | grep -q '<html' || { echo "FAIL: response after swap doesn't look like a built page"; exit 1; }
echo "PASS: swap published and nginx followed it"

echo "== a failing --strict build must NOT take the site down =="
BROKEN_DIR=$(mktemp -d)
cp -a "$SRC"/. "$BROKEN_DIR"/
printf '\n[dangling](does-not-exist.md)\n' >> "$BROKEN_DIR/docs/README.md"
if build ccccccc "$BROKEN_DIR"; then
  echo "FAIL: broken build unexpectedly succeeded"; exit 1
fi
target=$(current_target)
[ "$target" = "/srv/builds/bbbbbbb" ] || { echo "FAIL: symlink moved to $target"; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/)
[ "$code" = "200" ] || { echo "FAIL: HTTP $code after broken build"; exit 1; }
echo "PASS: previous build still serving"

echo
echo "ALL PIPELINE CHECKS PASSED"
