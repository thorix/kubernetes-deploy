#!/usr/bin/env python3
"""
hygiene_lint.py — public-repo hygiene guard (Layer A).

Fails (exit 1) if a tracked file contains an ENVIRONMENT-SPECIFIC value that
belongs in the private config overlays, not in this public template repo:

  - a real domain  — any FQDN whose registrable domain is not an allowed
    placeholder or a known public/OSS host
  - a private IP   — an RFC1918 address that is not a documentation/TEST-NET
    range or a Kubernetes service/pod CIDR

Design note: this check never names your real domain/IPs (doing so would itself
be a leak). It works by *allow-listing* safe patterns and flagging everything
else — so it also catches values you haven't seen before. Server/node names
(arbitrary words) are intentionally NOT covered here; the private-side scan
(Layer B, in the config repo) handles those because it can safely know them.

Add legitimate public hosts to PUBLIC_ALLOW below, or append `# hygiene:allow`
to a specific line for a one-off exception.

Usage:
  hygiene_lint.py <files...>   # scan given files (pre-commit passes staged files)
  hygiene_lint.py --all        # scan all git-tracked files (CI)
"""
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

# --- Allowed registrable domains (last two labels) -------------------------
PUBLIC_ALLOW = {
    # RFC2606 / placeholders
    "example.com", "example.org", "example.net", "example.io", "example.lan",
    # code hosting + container/chart registries
    "github.com", "githubusercontent.com", "github.io", "ghcr.io", "docker.io",
    "quay.io", "gcr.io", "k8s.io", "googleapis.com", "gitlab.com", "bitbucket.org",
    "docker.com",
    # kubernetes / CNCF ecosystem + vendors seen in upstream charts & docs
    "kubernetes.io", "helm.sh", "cilium.io", "jetstack.io", "cert-manager.io",
    "prometheus.io", "grafana.com", "victoriametrics.com", "argoproj.io",
    "readthedocs.io", "sigs.k8s.io", "hashicorp.com", "letsencrypt.org",
    "cloudflare.com", "tailscale.com", "opnsense.org", "microsoftonline.com",
    "httpbin.org", "schemastore.org", "json-schema.org", "robusta.dev",
    "istio.io", "envoyproxy.io", "openebs.io", "longhorn.io",
    # project / annotation domains + common public clouds referenced in configs
    "gethomepage.dev", "renovatebot.com", "coreos.com", "x-k8s.io",
    "openshift.io", "gke.io", "aws.com", "amazonaws.com", "google.com",
    "azure.com", "visualstudio.com", "artifacthub.io",
    # public docs / vendor / reference sites cited in READMEs, charts, dashboards
    "amd.com", "civitai.com", "comfy.org", "microsoft.com", "force.com",
    "wolfpaulus.com", "goharbor.io", "holmesgpt.dev", "jsdelivr.net",
    "youtube.com", "talos.dev",
}

# Allowed hostname SUFFIXES (internal / placeholder zones — always safe)
ALLOWED_SUFFIXES = (".lan", ".local", ".internal", ".svc", ".cluster.local")

# TLDs we treat as "this is really a domain" (keeps file extensions like
# values.prod.yaml / deploy.sh / config.tpl and jsonpaths like
# metadata.labels.app from being mistaken for domains)
REAL_TLDS = {
    "io", "com", "net", "org", "dev", "cloud", "ai", "xyz", "tech", "info",
}

# --- Allowed IP networks (safe to appear in a public template) -------------
ALLOWED_NETS = [ipaddress.ip_network(n) for n in (
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24",  # RFC5737 TEST-NET
    "10.96.0.0/12", "10.244.0.0/16",                       # k8s svc / pod CIDR
    "127.0.0.0/8",                                         # loopback
    "0.0.0.0/8",                                           # "all interfaces"
)]
# Bare RFC1918 *block* addresses (the whole range) are generic, not a host leak
GENERIC_CIDRS = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "0.0.0.0/0"}

EXCLUDE_PATH_PARTS = ("/charts/", "charts/")  # vendored subcharts
EXCLUDE_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".woff", ".woff2",
    ".ttf", ".lock", ".tgz", ".gz", ".zip",
)

# Only flag domains that appear in a real hostname context — inside a URL, a
# protocol-relative //host, an @host (email/git), or the value of a hostname-ish
# key. This avoids Kubernetes API groups / CRD groups / apiVersions (bare
# identifiers like vault.banzaicloud.com), which are not infra leaks. The
# private-side scan (Layer B) still catches any bare real domain by exact match.
URL_HOST_RE = re.compile(r'(?:[a-zA-Z][a-zA-Z0-9+.\-]*://|//|@)([a-zA-Z0-9][a-zA-Z0-9.\-]*)')
KEY_HOST_RE = re.compile(
    r'\b(?:host|hostname|server|url|endpoint|instance|href|domain|fqdn|baseurl'
    r'|origin|address|source)\b["\']?\s*[:=]+[~\s]*["\']?'
    r'([a-zA-Z0-9][a-zA-Z0-9.\-]*\.[a-zA-Z]{2,24})', re.IGNORECASE)
IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b')
PLACEHOLDER_RE = re.compile(r'YOUR_[A-Z_]+|<[^>]+>|\bexample\b', re.IGNORECASE)

# IANA timezone (Region/City) — a location tell. The public base must use UTC;
# a real zone (e.g. Region/City) pinpoints the region. Matches the standard
# region prefixes so it won't fire on arbitrary paths.
TZ_RE = re.compile(
    r'\b(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe'
    r'|Indian|Pacific)/[A-Za-z_]+(?:/[A-Za-z_]+)?\b')


def extract_hosts(line: str):
    hosts = set()
    for m in list(URL_HOST_RE.finditer(line)) + list(KEY_HOST_RE.finditer(line)):
        h = m.group(1).rstrip('.')
        if '.' in h and not h.replace('.', '').isdigit():  # skip bare IPs
            hosts.add(h)
    return hosts


def registrable(host: str) -> str:
    parts = host.lower().rstrip('.').split('.')
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


def domain_ok(host: str) -> bool:
    h = host.lower().rstrip('.')
    if any(h.endswith(s) for s in ALLOWED_SUFFIXES):
        return True
    return registrable(h) in PUBLIC_ALLOW


def ip_ok(token: str) -> bool:
    try:
        if "/" in token:
            if token in GENERIC_CIDRS:
                return True
            ip = ipaddress.ip_network(token, strict=False).network_address
        else:
            ip = ipaddress.ip_address(token)
    except ValueError:
        return True  # not a valid IP (e.g. a version like 1.2.3.4-rc) — ignore
    if not ip.is_private:
        return True  # public IPs are out of scope for this layer
    return any(ip in n for n in ALLOWED_NETS)


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    return out.stdout.splitlines()


def vendored_subchart_dirs() -> list[str]:
    """Directories of Helm dependency charts (a Chart.yaml nested inside another
    chart's directory). These are upstream/vendored — not ours to keep clean."""
    tracked = subprocess.run(["git", "ls-files"], capture_output=True,
                             text=True).stdout.splitlines()
    chart_dirs = {str(Path(f).parent) for f in tracked
                  if Path(f).name == "Chart.yaml"}
    subs = []
    for d in chart_dirs:
        parts = Path(d).parts
        if any(str(Path(*parts[:i])) in chart_dirs for i in range(1, len(parts))):
            subs.append(d)
    return subs


def scan(files) -> list[tuple]:
    subcharts = vendored_subchart_dirs()
    violations = []
    for f in files:
        p = Path(f)
        if not p.is_file():
            continue
        if any(part in f for part in EXCLUDE_PATH_PARTS):
            continue
        if any(f == sd or f.startswith(sd + "/") for sd in subcharts):
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        try:
            lines = p.read_text(errors="replace").splitlines()
        except Exception:
            continue
        for n, line in enumerate(lines, 1):
            if "hygiene:allow" in line:
                continue
            for host in extract_hosts(line):
                if host.rsplit('.', 1)[-1].lower() not in REAL_TLDS:
                    continue
                if PLACEHOLDER_RE.search(host):
                    continue
                if not domain_ok(host):
                    violations.append((f, n, "domain", host))
            for m in IP_RE.finditer(line):
                tok = m.group(0)
                if not ip_ok(tok):
                    violations.append((f, n, "private-ip", tok))
            for m in TZ_RE.finditer(line):
                violations.append((f, n, "location/timezone", m.group(0)))
    return violations


def main(argv) -> int:
    files = tracked_files() if ("--all" in argv or not argv) else \
        [a for a in argv if not a.startswith("-")]
    violations = scan(files)
    if not violations:
        print("hygiene-lint: clean ✓")
        return 0
    print("hygiene-lint: FAILED — environment-specific values found.")
    print("These belong in the private config overlay, not this public repo:\n")
    for f, n, kind, val in violations:
        print(f"  {f}:{n}: {kind}: {val}")
    print(f"\n{len(violations)} finding(s). Fix by moving the real value to the "
          "matching\nkubernetes-config overlay and using a placeholder here "
          "(<app>.lan / 192.0.2.x).")
    print("If a value is genuinely public/safe: add it to PUBLIC_ALLOW in "
          "scripts/hygiene_lint.py,\nor append '# hygiene:allow' to the line.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
