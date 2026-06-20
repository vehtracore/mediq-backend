from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AIConsentStatusResponse(BaseModel):
    consent_granted: bool
    consent_version: Optional[str] = None
    consent_granted_at: Optional[datetime] = None
    consent_withdrawn_at: Optional[datetime] = None

