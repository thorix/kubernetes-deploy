#!/usr/bin/env python3
"""cve_delta.py: block a PR only when its image change INTRODUCES a critical finding.

For each image reference a PR changes, resolve the old and new refs to their
linux/amd64 platform digests, scan both with one Trivy DB, and compare the sets
of (VulnerabilityID, PkgName) keys at CRITICAL severity. The check fails only if
the new set holds a key the old set does not. Pilot reverts are exempt.

Output is one line, `cve-delta: <description>`, with the description taken from
a fixed list. Findings are never printed, summarised or uploaded; the digest
artifact holds YAML paths, refs and digests only.

Usage:
  cve_delta.py ci      # GitHub Actions; reads BASE_SHA, HEAD_SHA, PR_AUTHOR,
                       # PR_AUTHOR_TYPE, HEAD_REF, PILOT_APP_SLUG, ARTIFACT_PATH
  cve_delta.py pair --old <ref> --new <ref> [--verbose]
                    [--trivy-bin PATH] [--crane-bin PATH]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from typing import NamedTuple

import yaml

NO_CHANGE = "no image change"
CLEAN = "no new critical CVEs"
EXEMPT = "revert (exempt)"
INTRODUCED = "new critical CVEs"
FAILED = "scan failed"
PASS = (NO_CHANGE, CLEAN, EXEMPT)
FAIL = (INTRODUCED, FAILED)

PLATFORM = "linux/amd64"
# Marks an image value that is present but cannot be read as a reference. It
# only matters when it changes: a changed unparseable image fails closed.
UNPARSEABLE = "\0unparseable"

EXCLUDED_TOP = ("scripts", ".github", "simple-service", "chart-template")
# `_template` is a scaffold; `templates` holds Helm templates, which are not
# YAML until rendered (their images come from values files, scanned here).
EXCLUDED_ANY = ("_template", "templates")

REVERT_REF = re.compile(r"^pilot/revert-([0-9a-f]{40})$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
TAG = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
NAME_PART = re.compile(r"^[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*$")
HOST_PART = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)*"
                       r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?::[0-9]+)?$")


class Result(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


class Unparseable(Exception):
    """A changed file could not be loaded as YAML."""


class ScanError(Exception):
    """A registry, DB or scanner error: the verdict is `scan failed`."""


class Missing(Exception):
    """The registry says the ref does not exist."""


# ---- pure functions


def candidate_files(paths):
    """Changed paths that may declare images: YAML outside tooling and templates."""
    keep = []
    for path in paths:
        parts = path.split("/")
        if not path.endswith((".yaml", ".yml")):
            continue
        if parts[0] in EXCLUDED_TOP or any(p in EXCLUDED_ANY for p in parts[:-1]):
            continue
        keep.append(path)
    return keep


def parse_ref(ref):
    """`repo[:tag][@sha256:...]` -> (repo, tag, digest), or None if invalid."""
    if not isinstance(ref, str) or not ref or ref != ref.strip():
        return None
    name, digest = ref, None
    if "@" in ref:
        name, digest = ref.split("@", 1)
        if not DIGEST.match(digest):
            return None
    tag = None
    slash = name.rfind("/")
    colon = name.rfind(":")
    if colon > slash:
        name, tag = name[:colon], name[colon + 1:]
        if not TAG.match(tag):
            return None
    parts = name.split("/")
    first, rest = parts[0], parts[1:]
    if rest and HOST_PART.match(first) and ("." in first or ":" in first or first == "localhost"):
        components = rest
    else:
        components = parts
    if not components or not all(NAME_PART.match(p) for p in components):
        return None
    return name, tag, digest


def _scalar(value):
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float, str)):
        return str(value)
    return None


def _image_map(node):
    """A `{registry?, repository, tag, digest?}` map -> ref, UNPARSEABLE, or None."""
    repo = node.get("repository")
    if not isinstance(repo, str) or "tag" not in node or "://" in repo:
        return None
    tag, digest, registry = (_scalar(node.get(k)) for k in ("tag", "digest", "registry"))
    if tag is None or digest is None or registry is None:
        return UNPARSEABLE
    if not tag and not digest:
        return None                       # chart default: nothing declared here
    ref = (registry.rstrip("/") + "/" if registry else "") + repo
    ref += (":" + tag if tag else "") + ("@" + digest if digest else "")
    return ref if parse_ref(ref) else UNPARSEABLE


def _image_string(value, parent):
    """`image: repo:tag[@digest]`; an untagged `image:` takes a sibling `tag:`."""
    parsed = parse_ref(value)
    if parsed is None:
        return UNPARSEABLE
    tag = _scalar(parent.get("tag"))
    if parsed[1] is None and parsed[2] is None and tag:
        joined = value + ":" + tag
        return joined if parse_ref(joined) else UNPARSEABLE
    return value


def extract_images(doc, prefix=""):
    """Walk a YAML tree; return {yaml path: ref} for every declared image."""
    found = {}

    def walk(node, path):
        if isinstance(node, dict):
            ref = _image_map(node)
            if ref is not None:
                found[path] = ref
                return
            for key, value in node.items():
                sub = "%s.%s" % (path, key) if path else str(key)
                if key == "image" and isinstance(value, str):
                    found[sub] = _image_string(value, node)
                else:
                    walk(value, sub)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, "%s[%d]" % (path, i))

    walk(doc, prefix)
    return found


def load_images(text):
    """All images in one YAML text. Raises Unparseable on a YAML error."""
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError as exc:
        raise Unparseable() from exc
    if len(docs) == 1:
        return extract_images(docs[0])
    found = {}
    for i, doc in enumerate(docs):
        found.update(extract_images(doc, "[%d]" % i))
    return found


def pair_changes(base, head):
    """[(path, old ref or None, new ref)] for every image that differs at head."""
    return [(path, base.get(path), head[path])
            for path in sorted(head) if base.get(path) != head[path]]


def _critical_keys(rep):
    keys = set()
    for result in (rep or {}).get("Results") or []:
        for vuln in (result or {}).get("Vulnerabilities") or []:
            if vuln.get("Severity") == "CRITICAL":
                keys.add((vuln.get("VulnerabilityID"), vuln.get("PkgName")))
    return keys


def introduced(old, new):
    """CRITICAL (VulnerabilityID, PkgName) keys in the new report but not the old."""
    return _critical_keys(new) - _critical_keys(old)


def revert_exempt(author, author_type, head_ref, app_slug, is_ancestor, pr_pairs, commit_pairs):
    """True only for a pilot revert whose image changes exactly undo the reverted commit."""
    if not app_slug or author_type != "Bot" or author != app_slug + "[bot]":
        return False
    if not REVERT_REF.match(head_ref or "") or not is_ancestor:
        return False
    if not pr_pairs:
        return False
    inverse = {(path, new, old) for path, old, new in commit_pairs}
    return inverse == set(pr_pairs)


def verdict(pairs, *, unparseable=False, exempt=False, introduced_keys=None):
    """(passed, description). `introduced_keys` None means the scan did not finish."""
    if unparseable or any(UNPARSEABLE in (old, new) for _, old, new in pairs):
        return False, FAILED
    if not pairs:
        return True, NO_CHANGE
    if exempt:
        return True, EXEMPT
    if introduced_keys is None:
        return False, FAILED
    if introduced_keys:
        return False, INTRODUCED
    return True, CLEAN


# ---- I/O shell


def default_runner(argv):
    """Run argv (list, no shell) and capture everything: nothing reaches the log."""
    timeout = 900 if os.path.basename(argv[0]) == "trivy" else 120
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, shell=False,
                              timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return Result(127, "", "")
    return Result(proc.returncode, proc.stdout, proc.stderr)


def _git(runner, *args):
    res = runner(["git", *args])
    if res.returncode != 0:
        raise ScanError()
    return res.stdout


def _file_images(runner, sha, path):
    res = runner(["git", "show", "%s:%s" % (sha, path)])
    if res.returncode != 0:
        raise ScanError()
    return load_images(res.stdout)


def changed_pairs(runner, old_sha, new_sha):
    """(pairs, unparseable) for the image changes between two commits.

    Pair keys are `<file>:<yaml path>`. `old_sha` is used as given: callers pass
    the merge base (PR) or the parent (reverted commit).
    """
    raw = _git(runner, "diff", "--name-status", "--no-renames", "-z", old_sha, new_sha)
    fields = [f for f in raw.split("\0") if f]
    status_of = dict(zip(fields[1::2], fields[0::2]))
    pairs, unparseable = [], False
    for path in candidate_files(list(status_of)):
        status = status_of[path][:1]
        if status == "D":
            continue
        try:
            head = _file_images(runner, new_sha, path)
            base = {} if status == "A" else _file_images(runner, old_sha, path)
        except Unparseable:
            unparseable = True
            continue
        for key, old, new in pair_changes(base, head):
            pairs.append(("%s:%s" % (path, key), old, new))
    return pairs, unparseable


def _missing(stderr):
    return "MANIFEST_UNKNOWN" in stderr or "NOT_FOUND" in stderr


def resolve(runner, crane, ref):
    """(index digest, linux/amd64 platform digest). Raises Missing or ScanError."""
    digests = []
    for extra in ([], ["--platform", PLATFORM]):
        res = runner([crane, "digest", *extra, ref])
        if res.returncode != 0:
            raise Missing() if _missing(res.stderr) else ScanError()
        digest = res.stdout.strip()
        if not DIGEST.match(digest):
            raise ScanError()
        digests.append(digest)
    return digests[0], digests[1]


class Scanner:
    """One Trivy DB per run; each platform digest scanned at most once."""

    def __init__(self, runner, trivy, tmpdir):
        self.runner, self.trivy, self.tmpdir = runner, trivy, tmpdir
        self.db_ready = False
        self.cache = {}

    def scan(self, repo, digest):
        if not self.db_ready:
            if self.runner([self.trivy, "image", "--download-db-only"]).returncode != 0:
                raise ScanError()
            self.db_ready = True
        target = "%s@%s" % (repo, digest)
        if target not in self.cache:
            out = os.path.join(self.tmpdir, "scan-%d.json" % len(self.cache))
            res = self.runner([self.trivy, "image", "--skip-db-update", "--severity", "CRITICAL",
                               "--format", "json", "--quiet", "--output", out, target])
            if res.returncode != 0:
                raise ScanError()
            try:
                with open(out) as fh:
                    self.cache[target] = json.load(fh)
            except (OSError, ValueError) as exc:
                raise ScanError() from exc
            finally:
                if os.path.exists(out):
                    os.unlink(out)
        return self.cache[target]


def delta(scanner, crane, old_ref, new_ref):
    """Introduced keys for one pair, plus the digests. Raises ScanError."""
    new_parsed, old_parsed = parse_ref(new_ref), parse_ref(old_ref) if old_ref else None
    if new_parsed is None or (old_ref is not None and old_parsed is None):
        raise ScanError()
    try:
        new_index, new_platform = resolve(scanner.runner, crane, new_ref)
    except Missing as exc:
        raise ScanError() from exc
    old_platform, old_report = None, {}
    if old_ref is not None:
        try:
            _, old_platform = resolve(scanner.runner, crane, old_ref)
        except Missing:
            old_platform = None           # empty old set: every new finding counts
    new_report = scanner.scan(new_parsed[0], new_platform)
    if old_platform is not None:
        old_report = scanner.scan(old_parsed[0], old_platform)
    return {"introduced": introduced(old_report, new_report),
            "new_index_digest": new_index, "new_platform_digest": new_platform,
            "old_platform_digest": old_platform}


def _emit(out, description):
    out.write("cve-delta: %s\n" % description)
    return 0 if description in PASS else 1


def _exemption(env, runner, pairs):
    slug = env.get("PILOT_APP_SLUG", "")
    author, author_type, head_ref = (env.get(k, "") for k in ("PR_AUTHOR", "PR_AUTHOR_TYPE",
                                                             "HEAD_REF"))
    match = REVERT_REF.match(head_ref)
    if not slug or author_type != "Bot" or author != slug + "[bot]" or not match:
        return False
    sha = match.group(1)
    is_ancestor = runner(["git", "merge-base", "--is-ancestor", sha,
                          env["BASE_SHA"]]).returncode == 0
    if not is_ancestor:
        return False
    try:
        commit_pairs, unparseable = changed_pairs(runner, sha + "^", sha)
    except ScanError:
        return False
    if unparseable:
        return False
    return revert_exempt(author, author_type, head_ref, slug, is_ancestor, pairs, commit_pairs)


def run_ci(env, runner=default_runner, out=sys.stdout):
    crane, trivy = env.get("CRANE_BIN") or "crane", env.get("TRIVY_BIN") or "trivy"
    try:
        base, head = env["BASE_SHA"], env["HEAD_SHA"]
        merge_base = _git(runner, "merge-base", base, head).strip()
        pairs, unparseable = changed_pairs(runner, merge_base, head)
    except (KeyError, ScanError):
        return _emit(out, FAILED)
    if unparseable or not pairs or any(UNPARSEABLE in pair for pair in pairs):
        return _emit(out, verdict(pairs, unparseable=unparseable)[1])
    if _exemption(env, runner, pairs):
        return _emit(out, verdict(pairs, exempt=True)[1])
    keys, artifact = None, []
    try:
        with tempfile.TemporaryDirectory(prefix="cve-delta-") as tmp:
            scanner = Scanner(runner, trivy, tmp)
            keys = set()
            for path, old_ref, new_ref in pairs:
                got = delta(scanner, crane, old_ref, new_ref)
                keys |= got["introduced"]
                artifact.append({"path": path, "ref": new_ref,
                                 "index_digest": got["new_index_digest"],
                                 "platform_digest": got["new_platform_digest"]})
    except ScanError:
        keys = None
    desc = verdict(pairs, introduced_keys=keys)[1]
    if keys is not None and env.get("ARTIFACT_PATH"):
        with open(env["ARTIFACT_PATH"], "w") as fh:
            json.dump(artifact, fh, indent=2)
            fh.write("\n")
    return _emit(out, desc)


def run_pair(args, runner=default_runner, out=sys.stdout):
    try:
        with tempfile.TemporaryDirectory(prefix="cve-delta-") as tmp:
            got = delta(Scanner(runner, args.trivy_bin, tmp), args.crane_bin, args.old, args.new)
    except ScanError:
        return _emit(out, FAILED)
    ok, desc = verdict([("pair", args.old, args.new)], introduced_keys=got["introduced"])
    if not args.verbose:
        return _emit(out, desc)
    json.dump({"introduced": [list(k) for k in sorted(got["introduced"])],
               "old_platform_digest": got["old_platform_digest"],
               "new_platform_digest": got["new_platform_digest"]}, out)
    out.write("\n")
    return 0 if ok else 1


def main(argv=None, runner=default_runner, out=sys.stdout):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ci", help="PR check (reads the environment)")
    pair = sub.add_parser("pair", help="compare two refs")
    pair.add_argument("--old", required=True)
    pair.add_argument("--new", required=True)
    pair.add_argument("--verbose", action="store_true")
    pair.add_argument("--trivy-bin", default="trivy")
    pair.add_argument("--crane-bin", default="crane")
    args = parser.parse_args(argv)
    if args.cmd == "ci":
        return run_ci(dict(os.environ), runner=runner, out=out)
    return run_pair(args, runner=runner, out=out)


if __name__ == "__main__":
    sys.exit(main())
