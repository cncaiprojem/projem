from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[^@\s]*@([A-Za-z0-9.-]+)\.(\w+)")
_PHONE_RE = re.compile(r"\+?\d[\d\s-]{5,}")


def mask_email(text: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        u = m.group(1)
        d = m.group(2)
        tld = m.group(3)
        return f"{u}***@{d[:1]}***.{tld}"
    return _EMAIL_RE.sub(_repl, text)


def mask_phone(text: str) -> str:
    return _PHONE_RE.sub("***", text)


def mask_pii_in_json(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: mask_pii_in_json(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [mask_pii_in_json(x) for x in payload]
    if isinstance(payload, str):
        return mask_phone(mask_email(payload))
    return payload


