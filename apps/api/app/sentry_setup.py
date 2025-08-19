from __future__ import annotations

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from .config import settings


def setup_sentry() -> None:
    dsn: str | None = settings.sentry_dsn
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        environment=settings.env,
    )


