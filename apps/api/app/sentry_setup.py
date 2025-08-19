from __future__ import annotations

from typing import Optional

from sentry_sdk.integrations.fastapi import FastApiIntegration
import sentry_sdk

from .config import settings


def setup_sentry() -> None:
    dsn: Optional[str] = settings.sentry_dsn
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=0.1,
        environment=settings.env,
    )
