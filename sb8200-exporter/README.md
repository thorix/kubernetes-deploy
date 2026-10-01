# sb8200-exporter — decommissioned 2026-09-27

Retired when the connection moved to fibre. The Arris Surfboard SB8200 cable
modem it scraped is being switched off, so there is nothing left to poll.

`deploy.yaml` and `values.yaml` are removed. The directory stays only to hold
the dashboard.

**Removing those files did not turn anything off.** This file previously
claimed it did — that the generator stops emitting the Application, so the
Application disappears and `prune: true` removes the workload. Only the first
clause is true. The ApplicationSet runs with `applicationsSync: create-update`,
which creates and updates generated Applications and *never deletes* them, so
an Application whose `deploy.yaml` is gone is simply orphaned: still present,
still reconciling, still carrying `prune: true` and `selfHeal: true`.

It gets worse quietly. The multi-source definition lists three value files and
sets `ignoreMissingValueFiles: true`, so with all three gone the orphan does
not fail — it renders the shared chart with its bare defaults and deploys
whatever default image that chart carries. Here that produced a second pod
crash-looping against the chart's restrictive `securityContext`, while the
original pod kept running and kept polling a modem that no longer existed.

Four days of that went unnoticed, because every symptom of a half-removed app
looks like an app that is merely unhealthy.

Decommissioning properly takes a second step after the files are removed:

    kubectl -n argocd delete application <name>
    kubectl delete namespace <name>

Done here on 2026-10-01. Check `kubectl -n argocd get applications` against the
set of `*/deploy.yaml` paths if you want to find others; there were no other
orphans at that point.

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
and remain there until retention expires.

This was written as though it had stopped on 2026-09-27. It had not. Because
the Application was only orphaned and not removed, the original pod kept
running and kept failing against a modem that was gone — emitting that URL,
credential included, every 30 seconds for four more days. It stopped on
2026-10-01 when the Application and namespace were actually deleted.

So the volume is roughly four days of 30-second intervals rather than a handful
of lines, and the window is more recent than the retirement date above suggests.
The credential belongs to a device that is switched off, which makes it moot
rather than urgent — but treat it as disclosed, and do not reuse it if that
modem is ever returned to service.
