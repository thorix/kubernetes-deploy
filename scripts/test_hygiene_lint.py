#!/usr/bin/env python3
"""Tests for hygiene_lint host extraction (pure functions, no filesystem).

Regression origin: on 2026-09-07 five real `harbor.<realdomain>` values reached
this public repo and sat there for three weekly scans. The pre-commit hook and
the required CI check both passed, because the leaks were values of `repository:`
and `harborRegistries:` -- keys this linter did not consider hostname-ish -- and
neither had a scheme for the URL matcher to catch. These tests pin that gap shut.

Fixtures use the fictional `harbor.nonpublic.io`, which the linter treats exactly
like the real host (extracted, and absent from PUBLIC_ALLOW). Writing the real
domain here would itself be the leak these tests exist to prevent -- the hook
rejected an earlier draft of this file for precisely that.
"""
import unittest
import hygiene_lint as hl

# Stands in for the real registry host: a .io domain, so REAL_TLDS accepts it as
# a domain, and not in PUBLIC_ALLOW, so domain_ok() rejects it.
FAKE_REGISTRY = "harbor.nonpublic.io"  # hygiene:allow -- fictional, and the
# constant name itself is a registry-key context now, which is the linter
# working as intended rather than a leak.


class TestExtractHostsRegistryKeys(unittest.TestCase):
    """Container-registry keys are hostname contexts too."""

    def test_repository_key_with_path(self):
        # The exact shape that leaked: bare host, no scheme, path suffix.
        self.assertIn(
            FAKE_REGISTRY,
            hl.extract_hosts(f"  repository: {FAKE_REGISTRY}/library/image-inquisitor"),
        )

    def test_camelcase_registry_key_quoted(self):
        # `harborRegistries` -- a \b before "registries" never matches mid-word,
        # so the camelCase tail has to be handled explicitly.
        self.assertIn(
            FAKE_REGISTRY,
            hl.extract_hosts(f'harborRegistries: "{FAKE_REGISTRY}"'),
        )

    def test_camelcase_db_repository_key(self):
        self.assertIn(
            FAKE_REGISTRY,
            hl.extract_hosts(f"  dbRepository: {FAKE_REGISTRY}/ghcr-cache/aquasecurity/trivy-db"),
        )

    def test_registry_key(self):
        self.assertIn(FAKE_REGISTRY, hl.extract_hosts(f"registry: {FAKE_REGISTRY}"))

    def test_image_key_with_registry_host(self):
        self.assertIn(
            FAKE_REGISTRY,
            hl.extract_hosts(f"image: {FAKE_REGISTRY}/library/news-digest:v0.1.7"),
        )


class TestExtractHostsNoFalsePositives(unittest.TestCase):
    """The narrow key list exists to keep CRD/API groups out. Keep it that way."""

    def test_api_version_group_not_flagged(self):
        # apiVersion groups are bare identifiers, not infra leaks.
        self.assertEqual(hl.extract_hosts("apiVersion: vault.banzaicloud.com/v1alpha1"), set())

    def test_crd_group_not_flagged(self):
        self.assertEqual(hl.extract_hosts("  group: externaldns.k8s.io"), set())

    def test_bare_identifier_not_flagged(self):
        self.assertEqual(hl.extract_hosts("  app.kubernetes.io/name: thing"), set())

    def test_image_pull_policy_is_not_a_host_context(self):
        # `imagePullPolicy` starts with "image" but the key must be followed by
        # the separator, so it must not open a host context.
        self.assertEqual(hl.extract_hosts("  imagePullPolicy: IfNotPresent"), set())


class TestDomainOk(unittest.TestCase):
    """Public registries and placeholder suffixes must stay allowed, or the new
    keys above would turn every ordinary image reference into a finding."""

    def test_public_registries_allowed(self):
        for host in ("ghcr.io", "docker.io", "quay.io", "gcr.io", "registry.k8s.io"):
            self.assertTrue(hl.domain_ok(host), f"{host} should be allowed")

    def test_lan_placeholder_allowed(self):
        self.assertTrue(hl.domain_ok("harbor.lan"))

    def test_private_registry_rejected(self):
        self.assertFalse(hl.domain_ok(FAKE_REGISTRY))


if __name__ == "__main__":
    unittest.main()
