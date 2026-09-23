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


if __name__ == "__main__":
    unittest.main()
