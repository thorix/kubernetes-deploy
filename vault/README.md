

# Create Vault policy for reading tunnel credentials
vault policy write cloudflare-tunnel-ro - <<EOF
path "kv/data/cloudflare/tunnel-credentials" {
capabilities = ["read"]
}
EOF

# Create Kubernetes auth role (binds to external-secrets-operator service account)
vault write auth/kubernetes/role/cloudflare-tunnel \
    bound_service_account_names=external-secrets-operator \
    bound_service_account_namespaces=cloudflare-tunnel \
    policies=cloudflare-tunnel-ro \
    ttl=24h