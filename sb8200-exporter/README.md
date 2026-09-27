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

**This is the only remaining copy.** The dashboard is being deleted from Grafana
as well, so nothing here is a backup of something that still exists elsewhere.
It is kept because it may be worth sharing with anyone running the same modem,
and worth rereading when building something similar.

`id` is `null` and `schemaVersion` is 39, so it imports into any Grafana. It
carries no `__inputs` block, so on import it binds to the default Prometheus
datasource rather than prompting — repoint it if that is wrong.

Checked before committing rather than assumed: the only external names in the
file are `8.8.8.8`, `google.com`, `force.com` and `wolfpaulus.com` (the
exporter author's site). No private addresses, no internal hostnames, no
modem address. That matters because dashboards are normally kept out of git
here for exactly that reason — see the comment on `sidecar.dashboards` in
`grafana/values.yaml` — and this one is an exception only because it was
verified clean.

### If you are reusing this

It expects [wolfpaulus/sb8200-exporter](https://wolfpaulus.com) metrics plus a
`blackbox-ping` job for the Ping panel. Note the exporter's own metric names
carry upstream typos, and the dashboard matches them as-is:

    sb8200_dowmstream_correcteds_total     ("dowm")
    sb8200_downstrem_freq_hertz            ("downstrem")

Both are spelled that way by the exporter, so do not "fix" them in the queries
unless your exporter version spells them correctly.

## Also removed alongside this

- the `rye/sb8200-exporter/` overlay in the private config repo
- the modem's address from the `blackbox-ping` target list

## One loose end

The exporter logged its full request URL on every failure, and that URL carried
a base64 basic-auth credential for the modem. Those lines were shipped to Loki
and remain there until retention expires. The credential is for a device being
switched off, so it is moot rather than urgent — but if the modem is ever
returned to service, treat that credential as disclosed.
