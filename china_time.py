# -*- coding: utf-8 -*-
"""China Standard Time helpers without a system timezone database."""
from datetime import datetime, timedelta, timezone

_CHINA_TZ = timezone(timedelta(hours=8))


def china_now(instant=None):
    """Convert an instant to China Standard Time (UTC+8, no daylight saving)."""
    if instant is None:
        instant = datetime.now(timezone.utc)
    return instant.astimezone(_CHINA_TZ)
