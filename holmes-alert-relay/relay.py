#!/usr/bin/env python3
"""Alertmanager -> HolmesGPT -> Vikunja relay.

Alertmanager POSTs alerts to /alert. For each *firing* alert whose severity is
in RELAY_SEVERITIES, this asks HolmesGPT to investigate the root cause and files
it as a task in a Vikunja project — ONE task per distinct problem
(alertname+namespace), so a chronic issue is a single tracked ticket rather than
a stream of Slack messages. When the alert *resolves*, the task is closed.

Why tickets, not Slack: a Holmes root-cause is actionable work, and chronic
alerts (a pod OOMing for days) should be one item you track to done, not a
message re-posted every couple hours. The raw Alertmanager->Slack path still
fires independently as the real-time pager; this is the durable work-item side.

Design:
- Investigations are slow (local model), so ONE runs at a time (a single worker
  draining a bounded queue), de-duped by alertname+namespace for DEDUP_MINUTES.
- Task lifecycle: first firing -> create task with the root cause; a later
  firing while the task is still open -> add a comment (so you can see it's
  chronic); resolved -> mark the task done.
- stdlib only (runs on python:3.12-slim from a ConfigMap; no image build).
"""
from __future__ import annotations

import html
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
HOLMES_TIMEOUT = int(os.environ.get("HOLMES_TIMEOUT", "900"))  # seconds; local model is slow
RELAY_SEVERITIES = {s.strip().lower() for s in os.environ.get("RELAY_SEVERITIES", "critical").split(",") if s.strip()}
DEDUP_MINUTES = int(os.environ.get("DEDUP_MINUTES", "120"))

VIKUNJA_URL = os.environ.get("VIKUNJA_URL", "http://vikunja-simple-service.vikunja.svc:3456/api/v1")
VIKUNJA_TOKEN = os.environ.get("VIKUNJA_TOKEN", "")
VIKUNJA_PROJECT_ID = os.environ.get("VIKUNJA_PROJECT_ID", "8")

MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "20"))
PORT = int(os.environ.get("PORT", "8080"))

_work: "queue.Queue[dict]" = queue.Queue(maxsize=MAX_QUEUE)
_seen: dict[str, float] = {}          # dedup key -> last-enqueued epoch
_seen_lock = threading.Lock()


# ── HTTP helpers ─────────────────────────────────────────────────────────────

def _post_json(url: str, payload: dict, timeout: int) -> str:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _vk(method: str, path: str, payload: dict | None = None):
    """Call the Vikunja API. Returns parsed JSON (or {}). Raises on HTTP error."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        VIKUNJA_URL + path, data=data, method=method,
        headers={"Authorization": "Bearer " + VIKUNJA_TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        body = resp.read().decode("utf-8", "replace")
        return json.loads(body) if body.strip() else {}


# ── Alert -> Holmes ──────────────────────────────────────────────────────────

def _identity(alert: dict) -> tuple[str, str]:
    labels = alert.get("labels", {}) or {}
    return labels.get("alertname", "?"), labels.get("namespace", "")


def _prompt_for(alert: dict) -> str:
    name, ns = _identity(alert)
    labels = alert.get("labels", {}) or {}
    ann = alert.get("annotations", {}) or {}
    obj = labels.get("pod") or labels.get("deployment") or labels.get("statefulset") or labels.get("instance") or ""
    where = f" in namespace '{ns}'" if ns else ""
    where += f" for '{obj}'" if obj else ""
    summary = ann.get("summary") or ann.get("description") or ""
    return (
        f"A Kubernetes alert '{name}'{where} is firing. Details: {summary}\n"
        f"Alert labels: {json.dumps(labels)}\n"
        "Investigate the root cause using pod status, recent events, logs, and "
        "relevant Prometheus metrics.\n\n"
        "Respond with a SHORT answer (at most ~6 sentences): one line naming the "
        "most likely root cause, a couple of supporting facts, and one concrete "
        "next action. Write plain prose only — do NOT include raw tool output, log "
        "excerpts, counts, timestamps, or section headings. If the available data "
        "is insufficient to determine a cause, say so in one line.\n\n"
        "IMPORTANT: if a tool query returns no results or errors, treat that data "
        "as UNAVAILABLE, not as evidence of absence. Do NOT conclude that a "
        "resource (pod, deployment, etc.) is missing, deleted, or does not exist "
        "unless a successful query explicitly confirms it — otherwise say the data "
        "could not be retrieved."
    )


def _ask_holmes(alert: dict) -> str:
    prompt = _prompt_for(alert)
    raw = _post_json(HOLMES_URL, {"ask": prompt, "stream": False}, timeout=HOLMES_TIMEOUT)
    analysis = (json.loads(raw).get("analysis") or "").strip()
    if not analysis:  # the local model occasionally returns an empty analysis
        log.info("empty analysis; retrying once")
        raw = _post_json(HOLMES_URL, {"ask": prompt, "stream": False}, timeout=HOLMES_TIMEOUT)
        analysis = (json.loads(raw).get("analysis") or "").strip()
    return analysis or "(Holmes returned no analysis after a retry)"


# ── Vikunja task lifecycle ───────────────────────────────────────────────────

def _task_title(alert: dict) -> str:
    name, ns = _identity(alert)
    return f"[alert] {name}" + (f" — {ns}" if ns else "")


def _find_open_task(title: str) -> dict | None:
    try:
        tasks = _vk("GET", f"/projects/{VIKUNJA_PROJECT_ID}/tasks?per_page=100&filter_include_nulls=false")
    except Exception as exc:  # noqa: BLE001
        log.error("vikunja list failed: %s", exc)
        return None
    for t in tasks or []:
        if t.get("title") == title and not t.get("done"):
            return t
    return None


def _description(alert: dict, analysis: str) -> str:
    name, ns = _identity(alert)
    ann = alert.get("annotations", {}) or {}
    summary = ann.get("summary") or ann.get("description") or ""
    parts = [f"<p><b>Alert:</b> {html.escape(name)}" + (f" in <code>{html.escape(ns)}</code>" if ns else "") + "</p>"]
    if summary:
        parts.append(f"<p><b>Summary:</b> {html.escape(summary)}</p>")
    parts.append("<p><b>HolmesGPT root cause:</b><br>" + html.escape(analysis).replace("\n", "<br>") + "</p>")
    parts.append("<p><i>Auto-filed by holmes-alert-relay; closes when the alert resolves.</i></p>")
    return "".join(parts)


def _upsert_task(alert: dict, analysis: str) -> None:
    title = _task_title(alert)
    existing = _find_open_task(title)
    if existing:
        comment = "<p><b>Still firing.</b> Latest HolmesGPT diagnosis:<br>" + \
                  html.escape(analysis).replace("\n", "<br>") + "</p>"
        _vk("PUT", f"/tasks/{existing['id']}/comments", {"comment": comment})
        log.info("commented on task %s (%s)", existing["id"], title)
    else:
        t = _vk("PUT", f"/projects/{VIKUNJA_PROJECT_ID}/tasks",
                {"title": title, "description": _description(alert, analysis)})
        log.info("created task %s (%s)", (t or {}).get("id"), title)


def _close_task(alert: dict) -> None:
    title = _task_title(alert)
    t = _find_open_task(title)
    if not t:
        return
    try:
        _vk("POST", f"/tasks/{t['id']}", {"id": t["id"], "done": True})
        log.info("closed task %s (%s) — alert resolved", t["id"], title)
    except Exception as exc:  # noqa: BLE001
        log.error("vikunja close failed for %s: %s", title, exc)


# ── Worker + queue (firing investigations) ───────────────────────────────────

def _investigate(alert: dict) -> None:
    name, ns = _identity(alert)
    started = time.time()
    log.info("investigating alert=%s ns=%s", name, ns)
    try:
        analysis = _ask_holmes(alert)
    except Exception as exc:  # noqa: BLE001
        log.error("holmes investigation failed for %s: %s", name, exc)
        analysis = f"(HolmesGPT investigation failed: {exc})"
    try:
        _upsert_task(alert, analysis)
    except Exception as exc:  # noqa: BLE001 - never let Vikunja errors kill the worker
        log.error("vikunja upsert failed for %s: %s", name, exc)
    log.info("done alert=%s in %ss", name, int(time.time() - started))


def _worker() -> None:
    while True:
        alert = _work.get()
        try:
            _investigate(alert)
        finally:
            _work.task_done()


def _enqueue(alert: dict) -> str:
    name, ns = _identity(alert)
    fp = f"{name}/{ns}"  # identity de-dup (fingerprint churns on pod restarts)
    now = time.time()
    with _seen_lock:
        if now - _seen.get(fp, 0) < DEDUP_MINUTES * 60:
            return "deduped"
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


# ── HTTP server ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        return

    def _send(self, code: int, body: str = "") -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if body:
            self.wfile.write(body.encode())

    def do_GET(self):
        self._send(200, "ok") if self.path == "/healthz" else self._send(404, "not found")

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
        counts = {"queued": 0, "deduped": 0, "queue-full": 0, "resolved": 0, "skipped": 0}
        for alert in data.get("alerts", []) or []:
            sev = (alert.get("labels", {}) or {}).get("severity", "").lower()
            if sev not in RELAY_SEVERITIES:
                counts["skipped"] += 1
                continue
            status = alert.get("status")
            if status == "firing":
                counts[_enqueue(alert)] += 1
            elif status == "resolved":
                _close_task(alert)      # fast (no investigation); close the tracked task
                counts["resolved"] += 1
            else:
                counts["skipped"] += 1
        log.info("webhook: %s (qsize=%d)", counts, _work.qsize())
        self._send(200, json.dumps(counts))


def main() -> None:
    threading.Thread(target=_worker, daemon=True).start()
    log.info(
        "relay up on :%d holmes=%s severities=%s dedup=%dm vikunja=%s project=%s token=%s",
        PORT, HOLMES_URL, sorted(RELAY_SEVERITIES), DEDUP_MINUTES, VIKUNJA_URL,
        VIKUNJA_PROJECT_ID, "set" if VIKUNJA_TOKEN else "MISSING",
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
