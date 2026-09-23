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
- Task lifecycle (one task per alertname+namespace):
    * first firing            -> create task with the root cause
    * fires again while open   -> add a comment (so you can see it's chronic)
    * fires again after close  -> reopen the same task if it closed within
                                  REOPEN_WINDOW_HOURS, else a fresh task
    * resolved                 -> arm a close; the reaper closes the task only
                                  after CLOSE_GRACE_MINUTES of staying resolved,
                                  and any firing in that window cancels it (so a
                                  flapping alert never churns tickets).
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
from datetime import datetime, timezone
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

# A resolved alert does not close its task immediately: it arms a pending close
# that the reaper acts on only after the problem has stayed resolved this long.
# Any firing in the window cancels it, so a flapping alert never churns tickets.
CLOSE_GRACE_MINUTES = int(os.environ.get("CLOSE_GRACE_MINUTES", "10"))
# When a problem fires again after its task was closed, reopen that task (instead
# of creating a new one) if it was closed within this many hours. Beyond the
# window, a recurrence gets a fresh ticket with its own investigation history.
REOPEN_WINDOW_HOURS = int(os.environ.get("REOPEN_WINDOW_HOURS", "24"))

MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "20"))
PORT = int(os.environ.get("PORT", "8080"))

_work: "queue.Queue[dict]" = queue.Queue(maxsize=MAX_QUEUE)
_seen: dict[str, float] = {}          # dedup key -> last-enqueued epoch
_seen_lock = threading.Lock()
# identity key -> (close-deadline epoch, task title). A resolved alert arms an
# entry here; a firing cancels it; the reaper closes the task once the deadline
# passes. Guarded by _pending_lock.
_pending_close: dict[str, tuple[float, str]] = {}
_pending_lock = threading.Lock()


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


def _scope(alert: dict) -> str:
    """The discriminator that makes a ticket title unique.

    namespace is the right scope for a workload alert and stays stable when a
    pod is replaced. But blackbox/probe alerts carry NO namespace, so scoping on
    it alone collapsed every EndpointDown into one ticket: on 2026-09-22 a single
    "[alert] EndpointDown" stood for both llama.thorix.io and 100.98.214.1, with
    an analysis that discussed only the first, and fixing one could never close
    it. Fall back to the target's own identity so each gets its own ticket.

    Order matters -- namespace first, so a workload alert that also carries an
    instance label is not retitled every time the pod IP changes.
    """
    labels = alert.get("labels", {}) or {}
    for key in ("namespace", "instance", "target", "job"):
        value = labels.get(key)
        if value:
            return value
    return ""


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
    name, _ = _identity(alert)
    scope = _scope(alert)
    return f"[alert] {name}" + (f" — {scope}" if scope else "")


def _ident_key(alert: dict) -> str:
    # Must split exactly the way _task_title does, or resolving one target would
    # arm a pending close against a different target's ticket.
    name, _ = _identity(alert)
    return f"{name}/{_scope(alert)}"


def _find_tasks(title: str) -> tuple[dict | None, dict | None]:
    """Return (open task, most-recently-closed task) matching this title.

    Vikunja's project task list includes done tasks, so one call finds both.
    """
    try:
        tasks = _vk("GET", f"/projects/{VIKUNJA_PROJECT_ID}/tasks?per_page=100&filter_include_nulls=false")
    except Exception as exc:  # noqa: BLE001
        log.error("vikunja list failed: %s", exc)
        return None, None
    open_t: dict | None = None
    closed_t: dict | None = None
    for t in tasks or []:
        if t.get("title") != title:
            continue
        if not t.get("done"):
            open_t = open_t or t
        elif closed_t is None or (t.get("done_at") or "") > (closed_t.get("done_at") or ""):
            closed_t = t  # done_at is RFC3339 Z, so string compare orders by time
    return open_t, closed_t


def _within_reopen_window(task: dict) -> bool:
    try:
        dt = datetime.fromisoformat((task.get("done_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - dt).total_seconds() <= REOPEN_WINDOW_HOURS * 3600


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


def _analysis_html(analysis: str) -> str:
    return html.escape(analysis).replace("\n", "<br>")


def _upsert_task(alert: dict, analysis: str) -> None:
    title = _task_title(alert)
    open_t, closed_t = _find_tasks(title)
    if open_t:
        _vk("PUT", f"/tasks/{open_t['id']}/comments",
            {"comment": "<p><b>Still firing.</b> Latest HolmesGPT diagnosis:<br>"
                        + _analysis_html(analysis) + "</p>"})
        log.info("commented on task %s (%s)", open_t["id"], title)
        return
    if closed_t and _within_reopen_window(closed_t):
        tid = closed_t["id"]
        _vk("POST", f"/tasks/{tid}", {"id": tid, "done": False})  # reopen
        _vk("PUT", f"/tasks/{tid}/comments",
            {"comment": "<p><b>Alert refired — reopened.</b> Latest HolmesGPT diagnosis:<br>"
                        + _analysis_html(analysis) + "</p>"})
        log.info("reopened task %s (%s)", tid, title)
        return
    t = _vk("PUT", f"/projects/{VIKUNJA_PROJECT_ID}/tasks",
            {"title": title, "description": _description(alert, analysis)})
    log.info("created task %s (%s)", (t or {}).get("id"), title)


# ── Grace-period close (reaper) ──────────────────────────────────────────────

def _schedule_close(alert: dict) -> None:
    key, title = _ident_key(alert), _task_title(alert)
    with _pending_lock:
        if key in _pending_close:
            return  # already armed; grace counts from the first resolve
        _pending_close[key] = (time.time() + CLOSE_GRACE_MINUTES * 60, title)
    log.info("scheduled close of '%s' in %dm (alert resolved)", title, CLOSE_GRACE_MINUTES)


def _cancel_pending_close(alert: dict) -> None:
    key = _ident_key(alert)
    with _pending_lock:
        if _pending_close.pop(key, None):
            log.info("cancelled pending close of '%s' (still firing)", key)


def _close_task_by_title(title: str) -> None:
    open_t, _ = _find_tasks(title)
    if not open_t:
        return  # nothing open to close (already closed, or never created)
    try:
        _vk("POST", f"/tasks/{open_t['id']}", {"id": open_t["id"], "done": True})
        log.info("closed task %s (%s) — alert stayed resolved", open_t["id"], title)
    except Exception as exc:  # noqa: BLE001
        log.error("vikunja close failed for %s: %s", title, exc)


def _reaper() -> None:
    while True:
        time.sleep(30)
        now = time.time()
        due: list[str] = []
        with _pending_lock:
            for key, (deadline, title) in list(_pending_close.items()):
                if now >= deadline:
                    _pending_close.pop(key, None)
                    due.append(title)
        for title in due:
            try:
                _close_task_by_title(title)
            except Exception as exc:  # noqa: BLE001 - never let the reaper die
                log.error("reaper close failed for %s: %s", title, exc)


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
                _cancel_pending_close(alert)  # problem is back; don't let it close
                counts[_enqueue(alert)] += 1
            elif status == "resolved":
                _schedule_close(alert)        # arm a grace-period close (reaper acts)
                counts["resolved"] += 1
            else:
                counts["skipped"] += 1
        log.info("webhook: %s (qsize=%d)", counts, _work.qsize())
        self._send(200, json.dumps(counts))


def main() -> None:
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_reaper, daemon=True).start()
    log.info(
        "relay up on :%d holmes=%s severities=%s dedup=%dm grace=%dm reopen=%dh vikunja=%s project=%s token=%s",
        PORT, HOLMES_URL, sorted(RELAY_SEVERITIES), DEDUP_MINUTES, CLOSE_GRACE_MINUTES,
        REOPEN_WINDOW_HOURS, VIKUNJA_URL, VIKUNJA_PROJECT_ID, "set" if VIKUNJA_TOKEN else "MISSING",
    )
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
