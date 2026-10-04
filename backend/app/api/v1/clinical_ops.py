"""Token-protected operator trigger for due clinical source checks."""

import hmac
import os

from fastapi import APIRouter, Header, HTTPException

from app.services.clinical_source_updates import run_due_source_checks

router = APIRouter()


@router.post('/source-updates/check')
async def trigger_source_update_check(
    x_clinical_worker_token: str | None = Header(default=None),
) -> dict:
    expected = os.getenv('CLINICAL_SOURCE_UPDATE_WORKER_TOKEN', '')
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail='Source update worker unavailable')
    if not x_clinical_worker_token or not hmac.compare_digest(
            x_clinical_worker_token, expected):
        raise HTTPException(status_code=401, detail='Unauthorized')
    try:
        return await run_due_source_checks()
    except Exception:
        raise HTTPException(status_code=503, detail='Source update check unavailable')
