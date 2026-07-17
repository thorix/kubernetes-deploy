#!/usr/bin/env bash
# check_commit_tz.sh — fail if commit timestamps aren't UTC (+0000).
#
# Timezone offsets in git commit metadata (author/committer date) leak the
# committer's region even when file contents are clean — and GitHub exposes them
# via API + UI. Public repos should commit in UTC.
#
# Modes:
#   check_commit_tz.sh                 # pre-commit: the offset git WILL use now
#   check_commit_tz.sh <base>..<head>  # CI: every commit in the range
#
# Fix: commit with TZ=UTC. Add `export TZ=UTC` to your shell rc, or a git
# wrapper:  git() { TZ=UTC command git "$@"; }
# UTC in strict ISO 8601 can render as "Z" OR "+00:00" — git's %aI does the
# former on some versions/hosts (e.g. GitHub runners), the latter elsewhere.
# Accept every spelling of a zero offset; reject any real offset.
is_utc() {
  case "$1" in
    *Z|*+00:00|*+0000|*-00:00) return 0 ;;
    *) return 1 ;;
  esac
}
offset_of() { case "$1" in *Z) printf 'Z' ;; *) printf '%s' "${1: -6}" ;; esac; }

set -euo pipefail
bad=0
if [ "${1:-}" = "" ]; then
  for who in AUTHOR COMMITTER; do
    ident="$(git var "GIT_${who}_IDENT")"   # "name <email> 1720000000 +0000"
    off="${ident##* }"                       # last field: +hhmm
    if [ "$off" != "+0000" ]; then
      echo "✗ pending commit ${who} offset is ${off}, not UTC (+0000)"; bad=1
    fi
  done
else
  while IFS='|' read -r a c h; do
    if ! is_utc "$a" || ! is_utc "$c"; then
      echo "✗ ${h}: author=$(offset_of "$a") committer=$(offset_of "$c") (not UTC)"; bad=1
    fi
  done < <(git log --format='%aI|%cI|%h' "$1")
fi
if [ "$bad" = 1 ]; then
  echo ""
  echo "Commit timestamps must be UTC so they don't leak your region."
  echo "Fix: commit with TZ=UTC (e.g. 'export TZ=UTC' in your shell rc, or a"
  echo "wrapper:  git() { TZ=UTC command git \"\$@\"; })."
  exit 1
fi
echo "commit-tz: UTC ✓"
