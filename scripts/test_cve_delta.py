#!/usr/bin/env python3
# Note: test names avoid exactly 40 characters; the TruffleHog Lob detector
# reads `test_` plus 35 word characters as an API key.
"""Tests for cve_delta (stdlib unittest; no network, no crane, no trivy).

Every subprocess call goes through an injectable runner, so the CI and pair
flows run here against FakeRunner, which answers git, crane and trivy argv from
the synthetic fixtures in testdata/cve_delta/.
"""
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

import yaml

import cve_delta as cd

DATA = Path(__file__).resolve().parent / "testdata" / "cve_delta"
BASE = "b" * 40
HEAD = "c" * 40
MB = "d" * 40
SLUG = "example-pilot"
REVERTED = "e" * 40
APP = "registry.example.lan/team/app"
OLD_REF = APP + ":1.0.0"
NEW_REF = APP + ":1.0.1"


def text(name):
    return (DATA / name).read_text()


def report(name):
    return json.loads(text(name))


def fake_digest(ref, platform=False):
    seed = ref + ("|linux/amd64" if platform else "|index")
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


class FakeRunner:
    """Answers argv lists the way git, crane and trivy would."""

    def __init__(self, base_files, head_files, reports, *, status="M",
                 crane_errors=None, db_error=False, trivy_error=False,
                 ancestor=True, revert_parent_files=None, revert_files=None):
        self.trees = {MB: base_files, HEAD: head_files, BASE: base_files}
        if revert_files is not None:
            self.trees[REVERTED] = revert_files
            self.trees[REVERTED + "^"] = revert_parent_files
        self.reports = reports          # ref -> trivy report dict
        self.status = status
        self.crane_errors = crane_errors or {}
        self.db_error = db_error
        self.trivy_error = trivy_error
        self.ancestor = ancestor
        self.calls = []
        self.outputs = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        tool = os.path.basename(argv[0])
        if tool == "git":
            return self.git(argv[1:])
        if tool == "crane":
            return self.crane(argv[1:])
        if tool == "trivy":
            return self.trivy(argv[1:])
        raise AssertionError("unexpected argv %r" % argv)

    def git(self, a):
        if a[:2] == ["merge-base", "--is-ancestor"]:
            return cd.Result(0 if self.ancestor else 1, "", "")
        if a[0] == "merge-base":
            return cd.Result(0, MB + "\n", "")
        if a[0] == "diff":
            old, new = a[-2], a[-1]
            out = ""
            for path in sorted(set(self.trees[old]) | set(self.trees[new])):
                if path not in self.trees[old]:
                    st = "A"
                elif path not in self.trees[new]:
                    st = "D"
                elif self.trees[old][path] != self.trees[new][path]:
                    st = self.status
                else:
                    continue
                out += st + "\0" + path + "\0"
            return cd.Result(0, out, "")
        if a[0] == "show":
            sha, path = a[1].split(":", 1)
            tree = self.trees.get(sha, {})
            if path in tree:
                return cd.Result(0, tree[path], "")
            return cd.Result(128, "", "fatal: path does not exist")
        raise AssertionError("unexpected git %r" % a)

    def crane(self, a):
        self.assert_eq(a[0], "digest")
        ref = a[-1]
        if ref in self.crane_errors:
            return cd.Result(1, "", self.crane_errors[ref])
        return cd.Result(0, fake_digest(ref, "--platform" in a) + "\n", "")

    def trivy(self, a):
        self.assert_eq(a[0], "image")
        if "--download-db-only" in a:
            return cd.Result(1 if self.db_error else 0, "", "db error" if self.db_error else "")
        if self.trivy_error:
            return cd.Result(1, "", "scan error")
        out = a[a.index("--output") + 1]
        target = a[-1]
        for ref, rep in self.reports.items():
            if target.endswith("@" + fake_digest(ref, True)):
                Path(out).write_text(json.dumps(rep))
                self.outputs.append(out)
                return cd.Result(0, "", "")
        raise AssertionError("no report for target %r" % target)

    @staticmethod
    def assert_eq(a, b):
        if a != b:
            raise AssertionError("%r != %r" % (a, b))


def runner_for(fixture, **kw):
    base = {"app/values.yaml": text("base/values.yaml")}
    head = {"app/values.yaml": text("head/values.yaml")}
    new = {"introduces": "trivy_new_introduces.json",
           "clean": "trivy_new_clean.json"}[fixture]
    reports = {OLD_REF: report("trivy_old.json"), NEW_REF: report(new)}
    return FakeRunner(base, head, reports, **kw)


def ci_env(tmp, **over):
    env = {"BASE_SHA": BASE, "HEAD_SHA": HEAD, "PR_AUTHOR": "renovate[bot]",
           "PR_AUTHOR_TYPE": "Bot", "HEAD_REF": "renovate/app-1.x",
           "PILOT_APP_SLUG": "", "ARTIFACT_PATH": str(Path(tmp) / "cve-delta-digests.json")}
    env.update(over)
    return env


def run_ci(fixture=None, runner=None, env_over=None):
    """Run the CI flow; return (stdout text, exit code, artifact or None)."""
    runner = runner or runner_for(fixture)
    with tempfile.TemporaryDirectory() as tmp:
        env = ci_env(tmp, **(env_over or {}))
        buf = io.StringIO()
        code = cd.run_ci(env, runner=runner, out=buf)
        art = Path(env["ARTIFACT_PATH"])
        artifact = json.loads(art.read_text()) if art.exists() else None
    run_ci.last = (code, artifact, runner)
    return buf.getvalue()


def ci(fixture=None, runner=None, env_over=None):
    out = run_ci(fixture, runner, env_over)
    code, artifact, _ = run_ci.last
    return out, code, artifact


class TestCandidateFiles(unittest.TestCase):
    def test_candidate_files(self):
        paths = [
            "a/values.yaml", "a/values-extra.yml", "a/deploy.yaml",
            "scripts/testdata/x.yaml", ".github/workflows/ci.yml",
            "simple-service/values.yaml", "chart-template/values.yaml",
            "_template/values.yaml", "a/_template/values.yaml", "README.md",
            "a/templates/deployment.yaml", "a/index.html",
        ]
        self.assertEqual(cd.candidate_files(paths),
                         ["a/values.yaml", "a/values-extra.yml", "a/deploy.yaml"])


class TestExtractImages(unittest.TestCase):
    def test_repository_tag_map_and_image_strings(self):
        doc = yaml.safe_load(
            "image:\n  repository: registry.example.lan/team/app\n  tag: '1.2.3'\n"
            "job:\n  image: registry.example.lan/team/job:4.5\n"
            "numeric:\n  repository: registry.example.lan/team/num\n  tag: 16\n")
        self.assertEqual(cd.extract_images(doc), {
            "image": "registry.example.lan/team/app:1.2.3",
            "job.image": "registry.example.lan/team/job:4.5",
            "numeric": "registry.example.lan/team/num:16",
        })

    def test_digest_pinned_and_two_images_in_one_file(self):
        got = cd.extract_images(yaml.safe_load(text("images.yaml")))
        d3 = "sha256:" + "3" * 64
        d4 = "sha256:" + "4" * 64
        self.assertEqual(got, {
            "image": "registry.example.lan/team/app:1.2.3",
            "sidecar.image": "registry.example.lan/team/sidecar:2.0.0@" + d3,
            "containers[0].image": "registry.example.lan/team/worker:3.1@" + d4,
            "containers[1].image": "registry.example.lan:5000/team/tool:0.9",
            "containers[2].image": "busybox:1.36",
        })

    def test_unparseable_changed_image_fails_closed(self):
        base = {"app/values.yaml": "image: registry.example.lan/team/app:1.0.0\n"}
        for bad in ("image: !!bad\n", "image: [unclosed\n",
                    "image: 'Not A Valid Ref:1'\n"):
            with self.subTest(bad=bad):
                pairs, unparseable = cd.changed_pairs(
                    FakeRunner(base, {"app/values.yaml": bad}, {}), BASE, HEAD)
                self.assertEqual(cd.verdict(pairs, unparseable=unparseable),
                                 (False, "scan failed"))
        out, code, _ = ci(runner=FakeRunner(base, {"app/values.yaml": "image: !!bad\n"}, {}))
        self.assertEqual((out, code), ("cve-delta: scan failed\n", 1))

    def test_unchanged_unparseable_value_is_ignored(self):
        base = {"a/values.yaml": "image: 'Not A Ref'\nother: 1\n"}
        head = {"a/values.yaml": "image: 'Not A Ref'\nother: 2\n"}
        pairs, unparseable = cd.changed_pairs(FakeRunner(base, head, {}), BASE, HEAD)
        self.assertEqual((pairs, unparseable), ([], False))

    def test_untagged_image_string_takes_sibling_tag(self):
        doc = yaml.safe_load("exporter:\n  image: registry.example.lan/team/exp\n  tag: v1.2.0\n"
                             "pinned:\n  image: registry.example.lan/team/p:1\n  tag: v9\n")
        self.assertEqual(cd.extract_images(doc), {
            "exporter.image": "registry.example.lan/team/exp:v1.2.0",
            "pinned.image": "registry.example.lan/team/p:1"})

    def test_multi_document_paths(self):
        got = cd.load_images("image: x/a:1\n---\nimage: x/b:2\n")
        self.assertEqual(got, {"[0].image": "x/a:1", "[1].image": "x/b:2"})

    def test_parse_ref(self):
        d = "sha256:" + "a" * 64
        self.assertEqual(cd.parse_ref("nginx:1.31-alpine"), ("nginx", "1.31-alpine", None))
        self.assertEqual(cd.parse_ref("registry.example.lan:5000/team/app:1@" + d),
                         ("registry.example.lan:5000/team/app", "1", d))
        self.assertEqual(cd.parse_ref("registry.example.lan/team/app@" + d),
                         ("registry.example.lan/team/app", None, d))
        for bad in ("", "Has Space:1", "UPPER/app:1", "app:", "app@sha256:short"):
            with self.subTest(bad=bad):
                self.assertIsNone(cd.parse_ref(bad))


class TestPairs(unittest.TestCase):
    def test_no_image_change_passes(self):
        self.assertEqual(cd.pair_changes({"image": "x/a:1"}, {"image": "x/a:1"}), [])
        self.assertEqual(cd.verdict([]), (True, "no image change"))
        base = {"a/values.yaml": "image: x/a:1\nreplicas: 1\n", "README.md": "a"}
        head = {"a/values.yaml": "image: x/a:1\nreplicas: 2\n", "README.md": "b"}
        out, code, artifact = ci(runner=FakeRunner(base, head, {}))
        self.assertEqual((out, code, artifact), ("cve-delta: no image change\n", 0, None))

    def test_pair_changes_added_and_removed(self):
        got = cd.pair_changes({"a": "x/a:1", "gone": "x/g:1"},
                              {"a": "x/a:2", "new": "x/n:1"})
        self.assertEqual(got, [("a", "x/a:1", "x/a:2"), ("new", None, "x/n:1")])


class TestIntroduced(unittest.TestCase):
    def test_introduced_math(self):
        old, new = report("trivy_old.json"), report("trivy_new_introduces.json")
        self.assertEqual(cd.introduced(old, new),
                         {("CVE-0000-0002", "libexample"), ("CVE-0000-0001", "libthird")})
        self.assertEqual(cd.introduced(new, old), set())        # old superset
        self.assertEqual(cd.introduced(old, report("trivy_new_clean.json")), set())
        self.assertEqual(cd.introduced({}, {"Results": None}), set())

    def test_old_image_missing_counts_as_empty_old_set(self):
        for err in ("MANIFEST_UNKNOWN: manifest unknown", "GET ...: NOT_FOUND"):
            with self.subTest(err=err):
                runner = runner_for("clean", crane_errors={OLD_REF: err})
                runner.reports[NEW_REF] = report("trivy_old.json")
                out, code, artifact = ci(runner=runner)
                self.assertEqual((out, code), ("cve-delta: new critical CVEs\n", 1))
                scans = [c for c in runner.calls if c[0] == "trivy" and "--output" in c]
                self.assertEqual(len(scans), 1)        # only the new image is scanned

    def test_new_image_missing_is_scan_failed(self):
        runner = runner_for("clean", crane_errors={NEW_REF: "MANIFEST_UNKNOWN"})
        self.assertEqual(ci(runner=runner)[:2], ("cve-delta: scan failed\n", 1))

    def test_registry_or_db_error_gives_scan_failed(self):
        cases = {
            "registry": dict(crane_errors={OLD_REF: "UNAUTHORIZED: authentication required"}),
            "db": dict(db_error=True),
            "trivy": dict(trivy_error=True),
        }
        for name, kw in cases.items():
            with self.subTest(name=name):
                out, code, artifact = ci(runner=runner_for("clean", **kw))
                self.assertEqual((out, code, artifact), ("cve-delta: scan failed\n", 1, None))

    def test_db_downloaded_once_then_skips_update(self):
        runner = runner_for("clean")
        self.assertEqual(ci(runner=runner)[:2], ("cve-delta: no new critical CVEs\n", 0))
        trivy = [c for c in runner.calls if c[0] == "trivy"]
        self.assertEqual(trivy[0], ["trivy", "image", "--download-db-only"])
        self.assertEqual(sum("--download-db-only" in c for c in trivy), 1)
        for c in trivy[1:]:
            self.assertEqual(c[:9], ["trivy", "image", "--skip-db-update", "--severity",
                                     "CRITICAL", "--format", "json", "--quiet", "--output"])
            self.assertRegex(c[-1], r"^registry\.example\.lan/team/app@sha256:[0-9a-f]{64}$")
        self.assertIn(["crane", "digest", NEW_REF], runner.calls)
        self.assertIn(["crane", "digest", "--platform", "linux/amd64", NEW_REF], runner.calls)


class TestRevertExemption(unittest.TestCase):
    ARGS = dict(author=SLUG + "[bot]", author_type="Bot",
                head_ref="pilot/revert-" + REVERTED, app_slug=SLUG, is_ancestor=True,
                pr_pairs=[("f:image", "x/a:2", "x/a:1")],
                commit_pairs=[("f:image", "x/a:1", "x/a:2")])

    def test_revert_exemption_accept_and_reject(self):
        self.assertTrue(cd.revert_exempt(**self.ARGS))
        rejects = {
            "wrong author": dict(author="someone"),
            "human type": dict(author_type="User"),
            "wrong branch": dict(head_ref="pilot/revert-abc"),
            "other prefix": dict(head_ref="renovate/revert-" + REVERTED),
            "not ancestor": dict(is_ancestor=False),
            "non-inverse": dict(pr_pairs=[("f:image", "x/a:2", "x/a:0")]),
            "extra pair": dict(pr_pairs=[("f:image", "x/a:2", "x/a:1"), ("g", "x/b:1", "x/b:2")]),
            "empty slug": dict(app_slug="", author="[bot]"),
            "added image": dict(commit_pairs=[("f:image", None, "x/a:2")],
                                pr_pairs=[]),
        }
        for name, over in rejects.items():
            with self.subTest(name=name):
                self.assertFalse(cd.revert_exempt(**dict(self.ARGS, **over)))

    def revert_runner(self, ancestor=True):
        v1 = "image: registry.example.lan/team/app:1.0.0\n"
        v2 = "image: registry.example.lan/team/app:1.0.1\n"
        return FakeRunner({"app/values.yaml": v2}, {"app/values.yaml": v1}, {},
                          ancestor=ancestor,
                          revert_parent_files={"app/values.yaml": v1},
                          revert_files={"app/values.yaml": v2})

    def test_ci_revert_exempt(self):
        env = dict(PR_AUTHOR=SLUG + "[bot]", PR_AUTHOR_TYPE="Bot",
                   HEAD_REF="pilot/revert-" + REVERTED, PILOT_APP_SLUG=SLUG)
        runner = self.revert_runner()
        out, code, artifact = ci(runner=runner, env_over=env)
        self.assertEqual((out, code, artifact), ("cve-delta: revert (exempt)\n", 0, None))
        self.assertFalse(any(c[0] in ("crane", "trivy") for c in runner.calls))

    def test_ci_revert_not_exempt_without_slug(self):
        env = dict(PR_AUTHOR=SLUG + "[bot]", PR_AUTHOR_TYPE="Bot",
                   HEAD_REF="pilot/revert-" + REVERTED, PILOT_APP_SLUG="")
        runner = self.revert_runner()
        runner.reports = {"registry.example.lan/team/app:1.0.1": report("trivy_new_clean.json"),
                          "registry.example.lan/team/app:1.0.0": report("trivy_new_clean.json")}
        out, code, _ = ci(runner=runner, env_over=env)
        self.assertEqual((out, code), ("cve-delta: no new critical CVEs\n", 0))
        self.assertFalse(any("--is-ancestor" in c for c in runner.calls))


class TestCiOutput(unittest.TestCase):
    def test_artifact_schema_exact(self):
        out, code, artifact = ci("introduces")
        self.assertEqual(code, 1)
        self.assertEqual(len(artifact), 1)
        for item in artifact:
            self.assertEqual(set(item), {"path", "ref", "index_digest", "platform_digest"})
        self.assertEqual(artifact[0], {
            "path": "app/values.yaml:image", "ref": NEW_REF,
            "index_digest": fake_digest(NEW_REF), "platform_digest": fake_digest(NEW_REF, True)})
        self.assertEqual(ci("clean")[2][0]["ref"], NEW_REF)

    def test_ci_output_is_silent(self):
        out = run_ci(fixture="introduces")      # fake crane/trivy runners
        self.assertEqual(out.strip().splitlines(), ["cve-delta: new critical CVEs"])
        self.assertNotIn("CVE-", out)
        self.assertNotRegex(out.lower(), r"\d+\s*critical|critical\D{0,3}\d")
        _, artifact, _ = run_ci.last
        self.assertNotIn("CVE-", json.dumps(artifact))

    def test_ci_clean_passes(self):
        self.assertEqual(ci("clean")[:2], ("cve-delta: no new critical CVEs\n", 0))

    def test_temp_files_deleted(self):
        runner = runner_for("introduces")
        run_ci(runner=runner)
        self.assertEqual(len(runner.outputs), 2)
        for path in runner.outputs:
            self.assertFalse(os.path.exists(path))
            self.assertFalse(os.path.exists(os.path.dirname(path)))

    def test_every_description_is_from_the_fixed_list(self):
        self.assertEqual(set(cd.PASS) | set(cd.FAIL), {
            "no image change", "no new critical CVEs", "revert (exempt)",
            "new critical CVEs", "scan failed"})


class TestPairCli(unittest.TestCase):
    def run_pair(self, runner, *extra):
        buf = io.StringIO()
        code = cd.main(["pair", "--old", OLD_REF, "--new", NEW_REF, *extra],
                       runner=runner, out=buf)
        return buf.getvalue(), code

    def test_pair_line_and_custom_bins(self):
        runner = runner_for("introduces")
        out, code = self.run_pair(runner, "--trivy-bin", "/opt/x/trivy", "--crane-bin", "/opt/y/crane")
        self.assertEqual((out, code), ("cve-delta: new critical CVEs\n", 1))
        self.assertTrue(all(c[0] in ("/opt/x/trivy", "/opt/y/crane") for c in runner.calls))

    def test_pair_verbose_json(self):
        out, code = self.run_pair(runner_for("introduces"), "--verbose")
        self.assertEqual(code, 1)
        got = json.loads(out)
        self.assertEqual(set(got), {"introduced", "old_platform_digest", "new_platform_digest"})
        self.assertEqual(got["introduced"], [["CVE-0000-0001", "libthird"],
                                             ["CVE-0000-0002", "libexample"]])
        self.assertEqual(got["old_platform_digest"], fake_digest(OLD_REF, True))
        self.assertEqual(got["new_platform_digest"], fake_digest(NEW_REF, True))

    def test_pair_verbose_old_missing(self):
        runner = runner_for("clean", crane_errors={OLD_REF: "MANIFEST_UNKNOWN"})
        out, code = self.run_pair(runner, "--verbose")
        self.assertEqual((json.loads(out)["old_platform_digest"], code), (None, 0))

    def test_pair_bad_ref_is_scan_failed(self):
        buf = io.StringIO()
        code = cd.main(["pair", "--old", "Bad Ref", "--new", NEW_REF],
                       runner=runner_for("clean"), out=buf)
        self.assertEqual((buf.getvalue(), code), ("cve-delta: scan failed\n", 1))


if __name__ == "__main__":
    unittest.main()
