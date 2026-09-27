# sb8200-exporter — decommissioned 2026-09-27

Retired when the connection moved to fibre. The Arris Surfboard SB8200 cable
modem it scraped is being switched off, so there is nothing left to poll.

`deploy.yaml` and `values.yaml` are removed, which is what turns the service
off: the ApplicationSet generates one ArgoCD Application per `**/deploy.yaml`,
so with that file gone the Application disappears and `prune: true` removes the
workload. The directory stays only to hold the dashboard.

## dashboard.json

`Arris Surfboard SB8200`, exported from the Grafana DB before removal — ten
panels covering downstream SNR, receive power, corrected/uncorrectable error
rates, upstream transmit power, per-channel frequency, QAM modulation and
channel counts.

`id` is set to `null` so the file imports into any Grafana. It is **not**
provisioned: nothing here carries the `grafana_dashboard` label, and the
provisioner is configured with `disableDelete: true`, so the copy already in the
Grafana DB survives this removal and stays editable there. This file is the
durable copy, since the DB one has no data source once the exporter is gone.

Checked before committing: the JSON carries no addresses, hostnames or domains —
its datasource references are the generic `prometheus` and built-in `grafana`
entries. That matters because dashboards are normally kept out of git here for
exactly that reason (see the comment on `sidecar.dashboards` in
`grafana/values.yaml`); this one is an exception because it was verified clean.

## Also removed alongside this

- the `rye/sb8200-exporter/` overlay in the private config repo
- the modem's address from the `blackbox-ping` target list

## One loose end

The exporter logged its full request URL on every failure, and that URL carried
a base64 basic-auth credential for the modem. Those lines were shipped to Loki
and remain there until retention expires. The credential is for a device being
switched off, so it is moot rather than urgent — but if the modem is ever
returned to service, treat that credential as disclosed.
