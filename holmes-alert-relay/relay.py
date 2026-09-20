#!/usr/bin/env python3
"""Alertmanager -> HolmesGPT -> Slack relay.

Alertmanager POSTs firing alerts to /alert. For each firing alert whose
severity is in RELAY_SEVERITIES, this asks HolmesGPT to investigate the root
cause and posts the result to a Slack incoming webhook.

Design notes:
- HolmesGPT on the local 32B model takes ~7-8 min per investigation, so this
  runs ONE investigation at a time (a single worker draining a bounded queue),
  and de-dups by alert fingerprint for DEDUP_MINUTES so a flapping/repeating
  alert isn't investigated over and over.
- stdlib only (no pip deps) so it runs directly on python:3.12-slim from a
  ConfigMap, no image build.
- The raw Alertmanager->Slack alert still fires independently and instantly;
  this only adds a slower root-cause follow-up. If Holmes is down/slow, the
  alerting path is unaffected.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("relay")

HOLMES_URL = os.environ.get("HOLMES_URL", "http://holmesgpt-holmes.holmesgpt.svc/api/chat")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "")  # optional override; webhook has a default
RELAY_SEVERITIES = {s.strip().lower() for s in os.environ.get("RELAY_SEVERITIES", "critical").split(",") if s.strip()}
DEDUP_MINUTES = int(os.environ.get("DEDUP_MINUTES", "30"))
HOLMES_TIMEOUT = int(os.environ.get("HOLMES_TIMEOUT", "900"))  # seconds; 32B is slow
MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "20"))
PORT = int(os.environ.get("PORT", "8080"))

_work: "queue.Queue[dict]" = queue.Queue(maxsize=MAX_QUEUE)
_seen: dict[str, float] = {}          # fingerprint -> last-enqueued epoch
_seen_lock = threading.Lock()


def _post_json(url: str, payload: dict, timeout: int) -> str:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _slack(text: str) -> None:
    if not SLACK_WEBHOOK_URL:
        log.warning("no SLACK_WEBHOOK_URL set; would have posted:\n%s", text[:500])
        return
    payload: dict = {"text": text}
    if SLACK_CHANNEL:
        payload["channel"] = SLACK_CHANNEL
    try:
        _post_json(SLACK_WEBHOOK_URL, payload, timeout=15)
    except Exception as exc:  # noqa: BLE001 - never let Slack failure kill the worker
        log.error("slack post failed: %s", exc)


def _prompt_for(alert: dict) -> str:
    labels = alert.get("labels", {}) or {}
    ann = alert.get("annotations", {}) or {}
    name = labels.get("alertname", "unknown")
    ns = labels.get("namespace", "")
    obj = labels.get("pod") or labels.get("deployment") or labels.get("statefulset") or labels.get("instance") or ""
    where = f" in namespace '{ns}'" if ns else ""
    where += f" for '{obj}'" if obj else ""
    summary = ann.get("summary") or ann.get("description") or ""
    return (
        f"A Kubernetes alert '{name}'{where} is firing. Details: {summary}\n"
        f"Alert labels: {json.dumps(labels)}\n"
        "Investigate the root cause using pod status, recent events, logs, and "
        "relevant Prometheus metrics.\n\n"
        "Respond with a SHORT answer for a Slack message (at most ~6 sentences): "
        "one line naming the most likely root cause, a couple of supporting facts, "
        "and one concrete next action. Write plain prose only — do NOT include raw "
        "tool output, log excerpts, counts, timestamps, or section headings. If the "
        "available data is insufficient to determine a cause, say so in one line.\n\n"
        "IMPORTANT: if a tool query returns no results or errors, treat that data as "
        "UNAVAILABLE, not as evidence of absence. Do NOT conclude that a resource "
        "(pod, deployment, etc.) is missing, deleted, or does not exist unless a "
        "successful query explicitly confirms it — otherwise say the data could not "
        "be retrieved."
    )


def _investigate(alert: dict) -> None:
    labels = alert.get("labels", {}) or {}
    name = labels.get("alertname", "unknown")
    ns = labels.get("namespace", "")
    started = time.time()
    log.info("investigating alert=%s ns=%s fp=%s", name, ns, alert.get("fingerprint"))
    header = f":mag: *Holmes root-cause* for `{name}`" + (f" in `{ns}`" if ns else "")
    try:
        prompt = _prompt_for(alert)
        raw = _post_json(HOLMES_URL, {"ask": prompt, "stream": False}, timeout=HOLMES_TIMEOUT)
        analysis = (json.loads(raw).get("analysis") or "").strip()
        if not analysis:  # the local model occasionally returns an empty analysis
            log.info("empty analysis for %s; retrying once", name)
            raw = _post_json(HOLMES_URL, {"ask": prompt, "stream": False}, timeout=HOLMES_TIMEOUT)
            analysis = (json.loads(raw).get("analysis") or "").strip()
        analysis = analysis or "(Holmes returned no analysis after a retry)"
    except Exception as exc:  # noqa: BLE001
        log.error("holmes investigation failed for %s: %s", name, exc)
        _slack(f"{header}\n:warning: investigation failed: `{exc}`")
        return
    took = int(time.time() - started)
    _slack(f"{header}  _(took {took // 60}m{took % 60:02d}s)_\n{analysis}")
    log.info("posted analysis for alert=%s in %ss", name, took)


def _worker() -> None:
    while True:
        alert = _work.get()
        try:
            _investigate(alert)
        finally:
            _work.task_done()


def _enqueue(alert: dict) -> str:
    labels = alert.get("labels", {}) or {}
    # De-dup by alert IDENTITY (alertname+namespace), NOT fingerprint. A
    # crashlooping pod gets a new pod name on every restart, which changes the
    # fingerprint — so fingerprint de-dup would re-investigate the same problem
    # every ~restart. Identity de-dup investigates each distinct problem once
    # per DEDUP window.
    fp = labels.get("alertname", "?") + "/" + labels.get("namespace", "")
    now = time.time()
    with _seen_lock:
        last = _seen.get(fp, 0)
        if now - last < DEDUP_MINUTES * 60:
            return "deduped"
        # prune old fingerprints
        for k in [k for k, v in _seen.items() if now - v > DEDUP_MINUTES * 120]:
            _seen.pop(k, None)
        _seen[fp] = now
    try:
        _work.put_nowait(alert)
        return "queued"
    except queue.Full:
        with _seen_lock:
            _seen.pop(fp, None)
        return "queue-full"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # quiet default access logs
        return

    def _send(self, code: int, body: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if body:
            self.wfile.write(body.encode())

    def do_GET(self):
        if self.path == "/healthz":
            self._send(200, "ok")
        else:
            self._send(404, "not found")

    def do_POST(self):
        if self.path != "/alert":
            self._send(404, "not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, f"bad request: {exc}")
            return
        counts = {"queued": 0, "deduped": 0, "queue-full": 0, "skipped": 0}
        for alert in data.get("alerts", []) or []:
            sev = (alert.get("labels", {}) or {}).get("severity", "").lower()
            if alert.get("status") != "firing" or sev not in RELAY_SEVERITIES:
                counts["skipped"] += 1
                continue
            counts[_enqueue(alert)] += 1
        log.info("webhook: %s (qsize=%d)", counts, _work.qsize())
        self._send(200, json.dumps(counts))


def main() -> None:
    threading.Thread(target=_worker, daemon=True).start()
    log.info(
        "relay up on :%d holmes=%s severities=%s dedup=%dm slack=%s",
        PORT, HOLMES_URL, sorted(RELAY_SEVERITIES), DEDUP_MINUTES, "set" if SLACK_WEBHOOK_URL else "MISSING",
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
