#!/usr/bin/env python3
"""Tests for holmes-alert-relay ticket identity (pure functions, no network).

Regression origin: task titles were `alertname + namespace`. Blackbox/probe
alerts carry no namespace, so EVERY EndpointDown collapsed into a single ticket
titled "[alert] EndpointDown". On 2026-09-22 that one ticket stood for two
unrelated probe targets -- one a false alarm from probing a path the service
answers 415 to, the other genuinely unreachable for 7+ days -- while the Holmes
analysis attached to it discussed only the first. Fixing one could never close it.

Fixtures use placeholder values (RFC 5737 192.0.2.0/24 and a .lan host), not
the real targets. The pre-commit hygiene hook rejected an earlier
draft of this file for using the real ones, which is that guard working.
"""
import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "relay", os.path.join(os.path.dirname(__file__), "relay.py"))
relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relay)

PROBE_A = "https://probe-a.lan/health"   # stands in for an HTTP probe target
PROBE_B = "192.0.2.10"                            # stands in for an ICMP probe target


def alert(**labels):
    return {"labels": labels, "annotations": {}}


class TestTaskTitle(unittest.TestCase):
    def test_workload_alert_uses_namespace(self):
        # Unchanged behaviour: namespace is the right scope for workload alerts.
        self.assertEqual(
            relay._task_title(alert(alertname="ContainerOOMKilled", namespace="grafana-mcp")),
            "[alert] ContainerOOMKilled — grafana-mcp")

    def test_probe_alert_falls_back_to_instance(self):
        # The bug: no namespace, so this used to be a bare "[alert] EndpointDown".
        self.assertEqual(
            relay._task_title(alert(alertname="EndpointDown", instance=PROBE_A)),
            f"[alert] EndpointDown — {PROBE_A}")

    def test_two_probe_targets_get_distinct_titles(self):
        # The actual failure: these two collapsed into one ticket.
        a = relay._task_title(alert(alertname="EndpointDown", instance=PROBE_A))
        b = relay._task_title(alert(alertname="EndpointDown", instance=PROBE_B))
        self.assertNotEqual(a, b)

    def test_namespace_wins_over_instance(self):
        # A workload alert carries both; namespace is the more useful scope and
        # keeps the title stable when a pod IP changes.
        self.assertEqual(
            relay._task_title(alert(alertname="ContainerOOMKilled",
                                    namespace="opnsense-mcp", instance="192.0.2.30:8080")),
            "[alert] ContainerOOMKilled — opnsense-mcp")

    def test_falls_through_to_target_then_job(self):
        self.assertEqual(
            relay._task_title(alert(alertname="ProbeFailed", target=PROBE_B)),
            f"[alert] ProbeFailed — {PROBE_B}")
        self.assertEqual(
            relay._task_title(alert(alertname="ScrapeFailed", job="blackbox-ping")),
            "[alert] ScrapeFailed — blackbox-ping")

    def test_no_scope_labels_degrades_to_bare_title(self):
        self.assertEqual(relay._task_title(alert(alertname="SomethingOdd")), "[alert] SomethingOdd")

    def test_missing_alertname(self):
        self.assertEqual(relay._task_title(alert(namespace="x")), "[alert] ? — x")


class TestIdentKey(unittest.TestCase):
    """_ident_key drives the pending-close map, so it must split exactly the way
    the title does -- otherwise resolving one target would arm a close against
    another target's ticket."""

    def test_distinct_probe_targets_have_distinct_keys(self):
        a = relay._ident_key(alert(alertname="EndpointDown", instance=PROBE_A))
        b = relay._ident_key(alert(alertname="EndpointDown", instance=PROBE_B))
        self.assertNotEqual(a, b)

    def test_key_matches_title_scope(self):
        a = alert(alertname="ContainerOOMKilled", namespace="grafana-mcp", instance="192.0.2.20:80")
        self.assertIn("grafana-mcp", relay._ident_key(a))
        self.assertNotIn("192.0.2.20", relay._ident_key(a))


class TestPromptNamespace(unittest.TestCase):
    """The prompt says "in namespace '<x>'". That must stay a real namespace --
    the instance fallback is for titling only, and "in namespace
    'https://...'" would be a falsehood handed to the model."""

    def test_probe_alert_prompt_claims_no_namespace(self):
        p = relay._prompt_for(alert(alertname="EndpointDown", instance=PROBE_A))
        self.assertNotIn("in namespace", p)

    def test_workload_alert_prompt_keeps_namespace(self):
        p = relay._prompt_for(alert(alertname="ContainerOOMKilled", namespace="grafana-mcp"))
        self.assertIn("in namespace 'grafana-mcp'", p)


# ── Work-order path ──────────────────────────────────────────────────────────
import itertools
import queue as _q
import re as _re
import urllib.parse as _up
from datetime import datetime as _dt, timezone as _tz
from unittest import mock

NS_A, NS_B = "ns-a", "ns-b"
WO_TITLE = "[alert] ImageUpgradeAvailable — " + NS_A


def wo_alert(ns=NS_A, status="firing", images="img-one:1\nimg-two:2", summary="2 images", **extra):
    labels = {"alertname": "ImageUpgradeAvailable", "namespace": ns, "severity": "warning",
              "investigate": "false", "work_order": "cve-upgrade"}
    labels.update(extra)
    return {"status": status, "labels": labels,
            "annotations": {"summary": summary, "images": images, "runbook": "see runbook"}}


class FakeVikunja:
    """Stands in for relay._vk; records every call."""

    def __init__(self, tasks=None):
        self.tasks = list(tasks or [])
        self.comments = {}
        self.calls = []
        self.ids = itertools.count(1000)
        self.fail_page = None

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        p = _up.urlparse(path)
        q = _up.parse_qs(p.query)
        if method == "GET" and p.path == "/projects/8/tasks":
            if self.fail_page and int(q["page"][0]) == self.fail_page:
                raise RuntimeError("boom")
            s = q.get("s", [""])[0]
            per, page = int(q["per_page"][0]), int(q["page"][0])
            hits = [t for t in self.tasks if s in t["title"]]
            return hits[(page - 1) * per: page * per]
        if method == "PUT" and p.path == "/projects/8/tasks":
            t = {"id": next(self.ids), "title": payload["title"], "description": payload["description"],
                 "done": False}
            self.tasks.append(t)
            return t
        m = _re.fullmatch(r"/tasks/(\d+)/comments", p.path)
        if m:
            tid = int(m.group(1))
            if method == "GET":
                return list(self.comments.get(tid, []))
            self.comments.setdefault(tid, []).append({"comment": payload["comment"]})
            return {}
        m = _re.fullmatch(r"/tasks/(\d+)", p.path)
        if m and method == "POST":
            for t in self.tasks:
                if t["id"] == int(m.group(1)):
                    t["done"] = payload["done"]
                    t["done_at"] = _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if payload["done"] else ""
            return {}
        raise AssertionError(f"unexpected call {method} {path}")

    def puts(self):
        return [c for c in self.calls if c[0] == "PUT" and c[1] == "/projects/8/tasks"]

    def closes(self):
        return [c for c in self.calls if c[0] == "POST" and c[2] and c[2].get("done") is True]

    def n_comments(self):
        return sum(len(v) for v in self.comments.values())


def _no_holmes(*_a, **_k):
    raise AssertionError("Holmes must not be called")


class RelayCase(unittest.TestCase):
    def setUp(self):
        self.vk = FakeVikunja()
        self.am_alerts = []
        self.am_calls = []
        ps = [mock.patch.object(relay, "_vk", self.vk),
              mock.patch.object(relay, "_am_get", self._am),
              mock.patch.object(relay, "_ask_holmes", _no_holmes)]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        relay._pending_close.clear()
        relay._wo_close_enqueued.clear()
        relay._seen.clear()
        for qq in (relay._wo_queue, relay._work):
            while not qq.empty():
                qq.get_nowait()

    def _am(self, path):
        self.am_calls.append(path)
        if isinstance(self.am_alerts, Exception):
            raise self.am_alerts
        return self.am_alerts

    def drain(self):
        while not relay._wo_queue.empty():
            relay._wo_process(relay._wo_queue.get_nowait())

    def fire(self, a):
        relay._handle_alerts({"alerts": [a]})
        self.drain()

    def expire(self, minutes=181):
        """Run the reaper + worker with a clock `minutes` ahead of now."""
        t = __import__("time").time() + minutes * 60
        relay._reap_once(t)
        while not relay._wo_queue.empty():
            relay._wo_process(relay._wo_queue.get_nowait(), now=t)
        return t


class TestRouting(RelayCase):
    def test_work_order_firing_and_resolved_bypass_holmes(self):
        c = relay._handle_alerts({"alerts": [wo_alert()]})
        self.assertEqual(c["work-order"], 1)
        self.assertEqual(relay._wo_queue.get_nowait()[0], "upsert")
        self.assertTrue(relay._work.empty())
        before = __import__("time").time()
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        deadline, title, kind, ns = relay._pending_close[relay._ident_key(wo_alert())]
        self.assertEqual((kind, ns, title), ("wo", NS_A, WO_TITLE))
        self.assertAlmostEqual(deadline - before, 180 * 60, delta=5)
        self.assertTrue(relay._work.empty())
        self.assertEqual(relay._seen, {})

    def test_critical_non_work_order_unchanged(self):
        a = {"status": "firing", "labels": {"alertname": "PodNotReady", "namespace": "x", "severity": "critical"}}
        c = relay._handle_alerts({"alerts": [a]})
        self.assertEqual((c["queued"], c["work-order"]), (1, 0))
        self.assertEqual(relay._work.qsize(), 1)
        self.assertTrue(relay._wo_queue.empty())
        self.assertEqual(relay._handle_alerts({"alerts": [a]})["deduped"], 1)

    def test_critical_resolved_arms_close_with_holmes_grace(self):
        a = {"status": "resolved", "labels": {"alertname": "PodNotReady", "namespace": "x", "severity": "critical"}}
        before = __import__("time").time()
        self.assertEqual(relay._handle_alerts({"alerts": [a]})["resolved"], 1)
        d, title, kind, ns = relay._pending_close["PodNotReady/x"]
        self.assertEqual((kind, title), ("holmes", "[alert] PodNotReady — x"))
        self.assertAlmostEqual(d - before, relay.CLOSE_GRACE_MINUTES * 60, delta=5)

    def test_holmes_reaper_closes_as_before(self):
        self.vk.tasks.append({"id": 1, "title": "[alert] PodNotReady — x", "done": False})
        a = {"status": "resolved", "labels": {"alertname": "PodNotReady", "namespace": "x", "severity": "critical"}}
        relay._handle_alerts({"alerts": [a]})
        relay._reap_once(__import__("time").time() + 11 * 60)
        self.assertEqual(len(self.vk.closes()), 1)
        self.assertEqual(relay._pending_close, {})
        self.assertTrue(relay._wo_queue.empty())

    def test_warning_without_work_order_skipped(self):
        a = {"status": "firing", "labels": {"alertname": "X", "severity": "warning"}}
        self.assertEqual(relay._handle_alerts({"alerts": [a]})["skipped"], 1)

    def test_investigate_false_without_work_order_not_a_work_order(self):
        a = wo_alert()
        del a["labels"]["work_order"]
        self.assertFalse(relay._is_work_order(a))
        self.assertEqual(relay._handle_alerts({"alerts": [a]})["skipped"], 1)

    def test_enqueue_dedup_uses_ident_key(self):
        mk = lambda inst: {"status": "firing", "labels": {"alertname": "EndpointDown", "severity": "critical", "instance": inst}}
        c = relay._handle_alerts({"alerts": [mk(PROBE_A), mk(PROBE_B)]})
        self.assertEqual(c["queued"], 2)

    def test_mixed_batch_routes_each_alert(self):
        crit = {"status": "firing", "labels": {"alertname": "PodNotReady", "namespace": "x", "severity": "critical"}}
        warn = {"status": "firing", "labels": {"alertname": "Other", "severity": "warning"}}
        c = relay._handle_alerts({"alerts": [wo_alert(), wo_alert(status="resolved", ns=NS_B), crit, warn]})
        self.assertEqual((c["work-order"], c["queued"], c["skipped"]), (2, 1, 1))


class TestFindTasks(RelayCase):
    def test_find_open_task_on_page_two(self):
        self.vk.tasks = [{"id": i, "title": f"[alert] A — target n{i}", "done": False} for i in range(150)]
        self.vk.tasks[120]["title"] = "[alert] A — target"
        o, _ = relay._find_tasks("[alert] A — target")
        self.assertEqual(o["id"], 120)

    def test_done_match_never_returned_as_open(self):
        self.vk.tasks = [{"id": 1, "title": "t", "done": True, "done_at": "2026-01-01T00:00:00Z"},
                         {"id": 2, "title": "t", "done": True, "done_at": "2026-02-01T00:00:00Z"}]
        o, c = relay._find_tasks("t")
        self.assertIsNone(o)
        self.assertEqual(c["id"], 2)

    def test_search_failure_creates_nothing(self):
        self.vk.tasks = [{"id": i, "title": f"{WO_TITLE} n{i}", "done": False} for i in range(120)]
        self.vk.fail_page = 2
        self.fire(wo_alert())
        self.assertEqual(self.vk.puts(), [])

    def test_holmes_find_error_keeps_none_none(self):
        self.vk.fail_page = 1
        self.assertEqual(relay._find_tasks("x"), (None, None))


class TestDescription(RelayCase):
    def test_work_order_description_snapshot(self):
        a = wo_alert(images="img-one:1\n\nimg-two:2\n")
        h = relay._wo_hash(a)
        self.assertEqual(relay._wo_description(a), (
            "<p><b>Work order:</b> ImageUpgradeAvailable in <code>ns-a</code></p>"
            "<p><b>Summary:</b> 2 images</p>"
            "<p><b>Images:</b></p><ul><li><code>img-one:1</code></li><li><code>img-two:2</code></li></ul>"
            "<p><b>Runbook:</b> see runbook</p>"
            "<p><i>Auto-filed by holmes-alert-relay; closes when a rescan no longer sees these images.</i></p>"
            f"<!-- relay:wo h={h} -->"))
        self.assertRegex(h, r"^[0-9a-f]{12}$")

    def test_annotation_html_is_escaped(self):
        d = relay._wo_description(wo_alert(summary="<script>x</script>", images="<script>i</script>"))
        self.assertNotIn("<script>", d)
        self.assertIn("&lt;script&gt;", d)

    def test_visible_marker_style(self):
        with mock.patch.object(relay, "WORK_ORDER_MARKER_STYLE", "visible"):
            m = relay._wo_marker("0123456789ab")
        self.assertEqual(m, "<p>relay:wo h=0123456789ab</p>")
        self.assertEqual(relay._last_marker(m, []), "0123456789ab")

    def test_last_marker_prefers_comments_in_order(self):
        cs = [{"comment": "x <!-- relay:wo h=aaaaaaaaaaaa -->"}, {"comment": "<!-- relay:wo h=bbbbbbbbbbbb -->"}]
        self.assertEqual(relay._last_marker("<!-- relay:wo h=cccccccccccc -->", cs), "bbbbbbbbbbbb")
        self.assertEqual(relay._last_marker("<!-- relay:wo h=cccccccccccc -->", []), "cccccccccccc")
        self.assertIsNone(relay._last_marker("", []))


class TestUpsert(RelayCase):
    def test_identical_repeat_no_comment(self):
        self.fire(wo_alert())
        self.fire(wo_alert())
        self.assertEqual((len(self.vk.puts()), self.vk.n_comments()), (1, 0))

    def test_duplicate_firing_is_idempotent(self):
        relay._handle_alerts({"alerts": [wo_alert(), wo_alert()]})
        self.drain()
        self.assertEqual((len(self.vk.puts()), self.vk.n_comments()), (1, 0))

    def test_changed_images_one_comment(self):
        self.fire(wo_alert())
        self.fire(wo_alert(images="img-one:1\nimg-three:3"))
        self.assertEqual(self.vk.n_comments(), 1)
        self.fire(wo_alert(images="img-one:1\nimg-three:3"))
        self.assertEqual(self.vk.n_comments(), 1)

    def test_restart_keeps_hash(self):
        self.fire(wo_alert())
        spec = importlib.util.spec_from_file_location("relay2", relay.__file__)
        r2 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(r2)
        with mock.patch.object(r2, "_vk", self.vk):
            r2._wo_upsert(wo_alert())
        self.assertEqual((len(self.vk.puts()), self.vk.n_comments()), (1, 0))

    def test_reopen_always_comments(self):
        self.fire(wo_alert())
        self.vk.tasks[0].update(done=True, done_at=_dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self.fire(wo_alert())  # same hash: still comments on reopen
        self.assertFalse(self.vk.tasks[0]["done"])
        self.assertEqual(self.vk.n_comments(), 1)
        self.assertIn("relay:wo h=", self.vk.comments[self.vk.tasks[0]["id"]][0]["comment"])

    def test_old_closed_task_gets_fresh_ticket(self):
        self.vk.tasks.append({"id": 1, "title": WO_TITLE, "done": True, "done_at": "2020-01-01T00:00:00Z"})
        self.fire(wo_alert())
        self.assertEqual(len(self.vk.puts()), 1)


class TestClose(RelayCase):
    def test_refire_within_two_hours_reopens(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        self.expire()
        self.assertTrue(self.vk.tasks[0]["done"])
        self.fire(wo_alert())
        self.assertFalse(self.vk.tasks[0]["done"])
        self.assertEqual(self.vk.n_comments(), 1)

    def test_firing_inside_grace_cancels_close(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        self.fire(wo_alert())
        self.assertEqual(relay._pending_close, {})
        self.expire()
        self.assertEqual(self.vk.closes(), [])

    def test_firing_between_reaper_and_close_keeps_task_open(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        t = __import__("time").time() + 181 * 60
        relay._reap_once(t)
        self.assertEqual(relay._wo_queue.qsize(), 1)
        relay._reap_once(t)  # enqueued once only
        self.assertEqual(relay._wo_queue.qsize(), 1)
        relay._handle_alerts({"alerts": [wo_alert()]})  # firing hits first
        item = relay._wo_queue.get_nowait()
        close = item if item[0] == "close" else relay._wo_queue.get_nowait()
        relay._wo_process(close, now=t)
        self.assertEqual(self.vk.closes(), [])

    def test_reaper_never_closes_wo_directly(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        relay._reap_once(__import__("time").time() + 181 * 60)
        self.assertEqual(self.vk.closes(), [])
        self.assertEqual(len(relay._pending_close), 1)

    def test_close_search_error_rearms_then_closes(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        self.vk.fail_page = 1
        self.expire()
        self.assertEqual(self.vk.closes(), [])
        self.assertEqual(len(relay._pending_close), 1)
        self.vk.fail_page = None
        self.expire(minutes=181 * 2)
        self.assertEqual(len(self.vk.closes()), 1)
        self.assertEqual(relay._pending_close, {})

    def test_close_post_error_rearms_and_closes(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        orig = self.vk.__call__
        fail = {"on": True}

        def flaky(method, path, payload=None):
            if fail["on"] and method == "POST":
                raise RuntimeError("HTTP 500")
            return orig(method, path, payload)
        with mock.patch.object(relay, "_vk", flaky):
            self.expire()
            self.assertFalse(self.vk.tasks[0]["done"])
            self.assertEqual(len(relay._pending_close), 1)
            fail["on"] = False
            self.expire(minutes=181 * 2)
        self.assertTrue(self.vk.tasks[0]["done"])
        self.assertEqual(relay._pending_close, {})

    def test_resolve_reap_refire_resolve_reap_closes(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        t = __import__("time").time() + 181 * 60
        relay._reap_once(t)
        relay._handle_alerts({"alerts": [wo_alert()]})
        self.assertEqual(relay._wo_close_enqueued, set())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        relay._reap_once(t)
        self.assertEqual(relay._wo_close_enqueued, {relay._ident_key(wo_alert())})
        while not relay._wo_queue.empty():
            relay._wo_process(relay._wo_queue.get_nowait(), now=t)
        self.assertEqual(len(self.vk.closes()), 1)
        self.assertEqual((relay._pending_close, relay._wo_close_enqueued), ({}, set()))

    def test_refire_and_resolve_during_close_keeps_new_entry(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        orig = self.vk.__call__
        key = relay._ident_key(wo_alert())

        def mid(method, path, payload=None):
            r = orig(method, path, payload)
            if method == "POST":  # firing then resolved arrive during the close
                relay._handle_alerts({"alerts": [wo_alert()]})
                relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
            return r
        t = __import__("time").time() + 181 * 60
        relay._reap_once(t)
        with mock.patch.object(relay, "_vk", mid):
            relay._wo_process(relay._wo_queue.get_nowait(), now=t)
        self.assertIn(key, relay._pending_close)  # the newer entry survives

    def test_enqueued_flag_cleared_on_hold(self):
        self.fire(wo_alert())
        relay._handle_alerts({"alerts": [wo_alert(status="resolved")]})
        self.am_alerts = OSError("down")
        self.expire()
        self.assertEqual(relay._wo_close_enqueued, set())

    def _setup_two(self):
        for ns in (NS_A, NS_B):
            self.fire(wo_alert(ns=ns))
            relay._handle_alerts({"alerts": [wo_alert(ns=ns, status="resolved")]})

    def _hold(self, **labels):
        base = {"alertname": "ImageInquisitorInventoryIncomplete"}
        base.update(labels)
        self.am_alerts = [{"labels": base}]

    def _closed_titles(self):
        return {t["title"] for t in self.vk.tasks if t["done"]}

    def test_parse_hold_blocks_only_its_namespace(self):
        self._setup_two()
        self._hold(phase="parse", namespace=NS_B)
        self.expire()
        self.assertEqual(self._closed_titles(), {WO_TITLE})
        self.assertIn(relay._ident_key(wo_alert(ns=NS_B)), relay._pending_close)

    def test_list_hold_blocks_only_its_namespace(self):  # trufflehog:ignore
        self._setup_two()
        self._hold(phase="list", namespace=NS_B)
        self.expire()
        self.assertEqual(self._closed_titles(), {WO_TITLE})

    def test_hold_without_namespace_blocks_every_namespace(self):
        self._setup_two()
        self._hold(phase="parse")
        self.expire()
        self.assertEqual(self._closed_titles(), set())
        self.assertEqual(len(relay._pending_close), 2)

    def test_hold_rearms_with_grace(self):
        self._setup_two()
        self._hold(phase="parse")
        t = self.expire()
        for d, *_ in relay._pending_close.values():
            self.assertAlmostEqual(d - t, 180 * 60, delta=5)

    def test_am_unreachable_holds(self):
        self._setup_two()
        self.am_alerts = OSError("down")
        self.expire()
        self.assertEqual(self._closed_titles(), set())
        self.assertEqual(len(relay._pending_close), 2)

    def test_hold_clears_then_closes(self):
        self._setup_two()
        self._hold(phase="parse")
        t = self.expire()
        self.am_alerts = []
        self.expire(minutes=181 * 2)
        self.assertEqual(len(self._closed_titles()), 2)
        self.assertEqual(relay._pending_close, {})
        self.assertIn("alertname%3D%22ImageInquisitorInventoryIncomplete%22", self.am_calls[0])


class TestReconcile(RelayCase):
    def test_reconcile_keeps_firing_schedules_absent(self):
        self.vk.tasks = [
            {"id": 1, "title": "[alert] ImageUpgradeAvailable — ns-a", "done": False},
            {"id": 2, "title": "[alert] ImageUpgradeAvailable — ns-b", "done": False},
            {"id": 3, "title": "[alert] ImageUpgradeAvailable — ns-c", "done": True},
        ]
        self.am_alerts = [wo_alert(ns="ns-a")]
        self.assertEqual(relay._reconcile_work_orders(), 1)
        self.assertEqual(list(relay._pending_close), ["ImageUpgradeAvailable/ns-b"])
        self.assertEqual(relay._pending_close["ImageUpgradeAvailable/ns-b"][2:], ("wo", "ns-b"))
        self.assertIn("work_order%3D%22cve-upgrade%22", self.am_calls[0])
        # a future alert's key equals the scheduled one, so a refire cancels it
        relay._cancel_pending_close(wo_alert(ns="ns-b"))
        self.assertEqual(relay._pending_close, {})

    def test_reconcile_am_down_schedules_nothing(self):  # trufflehog:ignore
        self.vk.tasks = [{"id": 1, "title": WO_TITLE, "done": False}]
        self.am_alerts = OSError("down")
        self.assertEqual(relay._reconcile_work_orders(), 0)
        self.assertEqual(relay._pending_close, {})

    def test_reconcile_vikunja_down_schedules_nothing(self):
        self.vk.fail_page = 1
        self.am_alerts = []
        self.assertEqual(relay._reconcile_work_orders(), 0)

    def test_reconcile_never_lists_holmes_tasks(self):
        self.vk.tasks = [{"id": 1, "title": "[alert] PodNotReady — x", "done": False}]
        self.am_alerts = []
        self.assertEqual(relay._reconcile_work_orders(), 0)
        self.assertEqual(relay._pending_close, {})


if __name__ == "__main__":
    unittest.main()
