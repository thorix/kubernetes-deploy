#!/usr/bin/env bash
# Seed Vault with Harbor's internal secrets so the chart stops generating them per render.
# Writes kv/harbor/internal and kv/harbor/token. Prints key names and lengths only, never values.
# Refuses to overwrite existing paths. Needs: vault (logged in), helm, openssl, python3 + PyYAML.
# Run once before the first sync that uses harbor-internal/harbor-token (also on a from-scratch rebuild).
set -euo pipefail
umask 077

for p in kv/harbor/internal kv/harbor/token; do
  if vault kv metadata get "$p" >/dev/null 2>&1; then
    echo "refusing: $p already exists" >&2; exit 1
  fi
done

W=$(mktemp -d)
trap 'find "$W" -type f -exec shred -u {} + 2>/dev/null; rm -rf "$W"' EXIT
cd "$W"

# Random secrets (lengths the chart requires: 16, CSRF 32) and a new registry password.
python3 - <<'EOF'
import json, secrets, string
a = string.ascii_letters + string.digits
r = lambda n: "".join(secrets.choice(a) for _ in range(n))
d = {"secret": r(16), "CSRF_KEY": r(32), "JOBSERVICE_SECRET": r(16),
     "REGISTRY_HTTP_SECRET": r(16), "REGISTRY_PASSWD": r(32)}
json.dump(d, open("internal.json", "w"))
json.dump({"pw": d["REGISTRY_PASSWD"]}, open("hp-values.json", "w"))
EOF

# bcrypt htpasswd line via Helm's htpasswd function (same as the chart uses).
mkdir -p hp/templates
printf 'apiVersion: v2\nname: hp\nversion: 0.0.1\n' > hp/Chart.yaml
printf '%s\n' 'line: {{ htpasswd "harbor_registry_user" .Values.pw | quote }}' > hp/templates/out.yaml
helm template hp ./hp -f hp-values.json \
  | python3 -c "import sys, yaml; print(next(d for d in yaml.safe_load_all(sys.stdin) if d)['line'])" > htpasswd.line

python3 - <<'EOF'
import json
d = json.load(open("internal.json"))
h = open("htpasswd.line").read().strip()
assert h.startswith("harbor_registry_user:$2"), "htpasswd generation failed"
d["REGISTRY_HTPASSWD"] = h
json.dump(d, open("internal.json", "w"))
print("internal:", {k: len(v) for k, v in sorted(d.items())})
EOF

# Token-signing keypair: 10 years (the chart's auto-generated one lasts 1 year).
openssl req -x509 -newkey rsa:4096 -nodes -days 3650 -subj "/CN=harbor-token-ca" \
  -keyout tls.key -out tls.crt 2>/dev/null
python3 -c "import json; json.dump({'tls.crt': open('tls.crt').read(), 'tls.key': open('tls.key').read()}, open('token.json', 'w'))"
openssl x509 -in tls.crt -noout -enddate

vault kv put kv/harbor/internal @internal.json >/dev/null && echo "wrote kv/harbor/internal"
vault kv put kv/harbor/token @token.json >/dev/null && echo "wrote kv/harbor/token"
