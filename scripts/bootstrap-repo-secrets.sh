#!/usr/bin/env bash
# bootstrap-repo-secrets.sh
#
# Reads shared CI secrets from Vault and uploads them as GitHub repository
# secrets. Run this once when creating a new service repo.
#
# Usage:
#   ./scripts/bootstrap-repo-secrets.sh <owner/repo> [<owner/repo> ...]
#
# Prerequisites:
#   - vault CLI, authenticated  (vault login or VAULT_TOKEN set)
#   - gh CLI, authenticated     (gh auth login)
#   - VAULT_ADDR set (defaults to https://vault.lan)
#
# Secrets are read from: kv/github/ci-secrets
# Every field in that path is uploaded as a GitHub secret.

set -euo pipefail

VAULT_ADDR="${VAULT_ADDR:-https://vault.lan}"
export VAULT_ADDR

VAULT_PATH="kv/github/ci-secrets"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── prereq checks ─────────────────────────────────────────────────────────────

check_prereqs() {
  local ok=true

  if ! command -v vault &>/dev/null; then
    echo -e "${RED}Error: vault CLI not found${NC}"
    echo "  https://developer.hashicorp.com/vault/install"
    ok=false
  fi

  if ! command -v gh &>/dev/null; then
    echo -e "${RED}Error: gh CLI not found${NC}"
    echo "  https://cli.github.com"
    ok=false
  fi

  if ! command -v jq &>/dev/null; then
    echo -e "${RED}Error: jq not found${NC}"
    ok=false
  fi

  [[ "$ok" == true ]] || exit 1

  if ! vault status &>/dev/null; then
    echo -e "${RED}Error: cannot reach Vault at ${VAULT_ADDR}${NC}"
    echo "  Set VAULT_ADDR and run: vault login"
    exit 1
  fi

  if ! vault token lookup &>/dev/null; then
    echo -e "${RED}Error: not authenticated to Vault${NC}"
    echo "  Run: vault login"
    exit 1
  fi

  if ! gh auth status &>/dev/null; then
    echo -e "${RED}Error: not authenticated to GitHub${NC}"
    echo "  Run: gh auth login"
    exit 1
  fi
}

# ── main ──────────────────────────────────────────────────────────────────────

main() {
  if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <owner/repo> [<owner/repo> ...]" >&2
    exit 1
  fi

  check_prereqs

  echo -e "${YELLOW}Reading secrets from Vault: ${VAULT_PATH}${NC}"

  local raw
  raw=$(vault kv get -format=json "$VAULT_PATH") || {
    echo -e "${RED}Error: failed to read ${VAULT_PATH}${NC}"
    echo "  Make sure the path exists and your token has read access"
    exit 1
  }

  # Build key=value pairs from every field in the secret
  local pairs
  pairs=$(echo "$raw" | jq -r '.data.data | to_entries[] | "\(.key)=\(.value)"')

  local secret_count
  secret_count=$(echo "$pairs" | wc -l | tr -d ' ')
  echo -e "${GREEN}Found ${secret_count} secrets${NC}"
  echo ""

  for repo in "$@"; do
    echo -e "${YELLOW}Bootstrapping: ${repo}${NC}"

    # Verify the repo exists before uploading anything
    if ! gh repo view "$repo" &>/dev/null; then
      echo -e "${RED}  Error: repo not found or no access: ${repo}${NC}"
      continue
    fi

    while IFS='=' read -r key value; do
      gh secret set "$key" --repo "$repo" --body "$value"
      echo -e "  ${GREEN}✓${NC} $key"
    done <<< "$pairs"

    echo ""
  done

  echo -e "${GREEN}Done.${NC}"
}

main "$@"
