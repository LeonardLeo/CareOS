"""The two calendar-driven halves of background screening.

Both are thin wrappers over `careos.modules.credentialing.screening`, in the shape the runner
expects: one coroutine taking an `agency_id`, tenant-scoped, safe to run twice.

They are separate jobs because their cadences differ by three orders of magnitude and their
failure modes are unrelated. Polling for verdicts is a minutes-scale job whose failure leaves
a new hire unassignable; ordering re-screens is a daily job whose failure leaves an existing
caregiver working on a stale clearance. Merging them would force one interval on both, and
whichever it was would be wrong for the other.
"""

from __future__ import annotations

import uuid

from careos.modules.credentialing import screening


async def poll_screening_results(agency_id: uuid.UUID) -> screening.ScreeningRun:
    """Ask the vendor for verdicts on this agency's outstanding requests."""
    return await screening.poll_outstanding(agency_id)


async def order_screening_rescreens(agency_id: uuid.UUID) -> screening.ScreeningRun:
    """Re-order exclusion screening for caregivers whose clearance has gone stale."""
    return await screening.order_due_rescreens(agency_id)
