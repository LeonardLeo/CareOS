"""Regenerate the EVV conformance fixture.

    python -m careos.scripts.record_evv_conformance

Deliberately a separate command rather than an `--update` flag on the test. A snapshot test
whose fixture can be refreshed by the same invocation that checks it gets refreshed by
reflex when it fails, and the whole value of this one is that a failure is a question
somebody has to answer: did we mean to change what the aggregator receives?
"""

from __future__ import annotations

import json
from pathlib import Path

from careos.integrations.evv.conformance import fixture_document

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "evv_conformance.json"


def main() -> int:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys and a trailing newline, so the diff is the content and never the ordering.
    FIXTURE.write_text(json.dumps(fixture_document(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
