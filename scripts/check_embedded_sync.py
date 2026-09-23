#!/usr/bin/env python3
"""Guard — a script that is ALSO embedded in a values.yaml must match its file.

holmes-alert-relay ships relay.py twice: as holmes-alert-relay/relay.py, which is
what you read and test, and embedded under configMap.files in its values.yaml,
which is what the pod actually runs. Editing only the first is a silent no-op at
runtime; editing only the second leaves the tests passing against dead code.

Both failure modes look exactly like success, which is the reason this exists.

Add a pair by appending to PAIRS. Exit 1 on any mismatch.
"""
import sys

import yaml

# (values.yaml, key path under the doc, file the embedded copy must equal)
PAIRS = [
    ("holmes-alert-relay/values.yaml",
     ("configMap", "files", "relay.py"),
     "holmes-alert-relay/relay.py"),
]


def dig(doc, path):
    for k in path:
        if not isinstance(doc, dict) or k not in doc:
            return None
        doc = doc[k]
    return doc


def main() -> int:
    failed = 0
    for values_path, key_path, file_path in PAIRS:
        try:
            with open(values_path, encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
            with open(file_path, encoding="utf-8") as fh:
                on_disk = fh.read()
        except OSError as exc:
            print(f"check-embedded-sync: cannot read: {exc}")
            failed = 1
            continue

        embedded = dig(doc, key_path)
        dotted = ".".join(key_path)
        if embedded is None:
            print(f"check-embedded-sync: {values_path}: no key {dotted}")
            failed = 1
            continue

        if embedded.strip() != on_disk.strip():
            e, d = embedded.strip().splitlines(), on_disk.strip().splitlines()
            print(f"check-embedded-sync: OUT OF SYNC")
            print(f"  {file_path} ({len(d)} lines) != {values_path}:{dotted} ({len(e)} lines)")
            for i, (a, b) in enumerate(zip(d, e), 1):
                if a != b:
                    print(f"  first difference at line {i}:")
                    print(f"    file:   {a.strip()[:90]}")
                    print(f"    values: {b.strip()[:90]}")
                    break
            print(f"  The pod runs the values.yaml copy. Copy the file into it before committing.")
            failed = 1

    if not failed:
        print("check-embedded-sync: embedded copies match their files ✓")
    return failed


if __name__ == "__main__":
    sys.exit(main())
