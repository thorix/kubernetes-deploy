# Grafana Dashboard Management

## Architecture

Custom dashboards live in the **Grafana database**, not in this repo.

Dashboard JSON tends to embed environment-specific and personal detail (probe
targets with real hostnames, panel names that describe a home setup, etc.), so
this public template repo does **not** ship dashboard JSON. Instead:

- **Custom dashboards** are created/edited in the Grafana UI and stored in
  Grafana's database (SQLite on the `grafana` PVC).
- **Durability** comes from the PVC being in **longhorn's `default` backup
  group** (`daily-backup`, 10:00 UTC, 7 retained) — so dashboards survive pod
  restarts and are recoverable from backup.
- **Community dashboards** stay as `gnetId` references in `values.yaml`
  (`dashboards.default.<name>.gnetId`) — those name no private data, so they're
  fine to keep in git.

The dashboard **sidecar remains enabled** (with `disableDeletion: true`), so a
future app *can* still ship a dashboard via a `grafana_dashboard: "1"` ConfigMap
if it contains no environment-specific data — but the default path for personal
dashboards is the DB.

> History: dashboards used to be provisioned from `grafana/dashboards/*.json`.
> They were moved to the DB on 2026-07-13 (personal content + a leaked domain in
> a probe query). `disableDeletion` was enabled first so removing the ConfigMaps
> left the existing dashboards intact in the DB.

## Creating / editing a dashboard

1. Build it in the Grafana UI (use the Grafana MCP below to develop queries).
2. Save it — it persists in the DB and is covered by the daily PVC backup.
3. Do **not** commit dashboard JSON with real hostnames/IPs/personal names to
   this repo; the hygiene lint will reject it.

## Grafana MCP (operational use)

The Grafana MCP server (`grafana-mcp`) provides read access to Grafana for Claude
Code sessions via the MCP gateway. Use it for:

- **Query development** — test PromQL/LogQL before saving to a dashboard
- **Debugging** — verify a datasource returns data, check metric/label names
- **Monitoring** — search dashboards, check alert states, inspect panels
- **Screenshots** — panel images for incident reports

**Do NOT use the MCP for production dashboard creation/updates.** The
`update-dashboard` tool is restricted to the "MCP Sandbox" folder for
experimentation only.

### MCP Tools Reference (via ops virtual server)

| Tool | Use For |
|------|---------|
| `grafana-search-dashboards` | Find dashboards by title/tag |
| `grafana-get-dashboard-by-uid` | Get full dashboard JSON |
| `grafana-list-prometheus-metric-names` | Discover available metrics |
| `grafana-list-prometheus-label-values` | Check label cardinality |
| `grafana-query-prometheus-histogram` | Test PromQL queries |
| `grafana-query-loki-logs` | Test LogQL queries |
| `grafana-list-alert-groups` | Check alert state |
| `grafana-get-panel-image` | Screenshot a panel |
