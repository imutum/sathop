"""Batch granule state transitions."""

from __future__ import annotations

from sathop.shared.state_machine import CANCELLABLE_STATES, RETRYABLE_STATES, GranuleState

from ..db import Granule


def cancel_granule_state(granule: Granule, now) -> bool:
    if granule.state not in CANCELLABLE_STATES:
        return False
    granule.state = GranuleState.BLACKLISTED.value
    granule.leased_by = None
    granule.lease_expires_at = None
    granule.updated_at = now
    return True


def retry_granule_state(granule: Granule, now) -> bool:
    if granule.state not in RETRYABLE_STATES:
        return False
    granule.state = GranuleState.PENDING.value
    granule.retry_count = 0
    granule.error = None
    granule.leased_by = None
    granule.lease_expires_at = None
    granule.updated_at = now
    return True
