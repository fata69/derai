"""Compare exported old/new job records while ignoring only random/write-time fields.

Accepts a JSON array or the JSON object emitted by `derai-scheduler preview`.
Never executes a worker or modifies a database.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

CONTRACT_FIELDS = (
    "tenant_id",
    "workspace_id",
    "kind",
    "parent_id",
    "name",
    "data",
    "status",
    "idempotency_key",
)


def canonical_records(path: Path) -> Counter[str]:
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = document["jobs"] if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise ValueError("Snapshot must contain an array of job records")
    canonical = []
    for row in rows:
        result = {key: row[key] for key in CONTRACT_FIELDS}
        result["data"] = (
            json.loads(result["data"]) if isinstance(result["data"], str) else result["data"]
        )
        if not isinstance(result["data"], dict):
            raise ValueError("Job data must decode to a JSON object")
        canonical.append(
            json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        )
    return Counter(canonical)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    args = parser.parse_args()
    try:
        old, new = canonical_records(args.old), canonical_records(args.new)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"match": False, "error": "Invalid or unreadable contract snapshot"}))
        return 2
    missing = sum((old - new).values())
    unexpected = sum((new - old).values())
    print(
        json.dumps(
            {
                "match": old == new,
                "old_count": old.total(),
                "new_count": new.total(),
                "missing": missing,
                "unexpected": unexpected,
            }
        )
    )
    return 0 if old == new else 1


if __name__ == "__main__":
    raise SystemExit(main())
