from __future__ import annotations

from app.logging.pii import mask_email, mask_phone, mask_pii_in_json


def test_mask_email():
    assert mask_email("alice@example.com") != "alice@example.com"


def test_mask_phone():
    assert mask_phone("+90 532 111 22 33") == "***"


def test_mask_json():
    data = {"email": "bob@domain.com", "tel": "+1 202-555-0178"}
    masked = mask_pii_in_json(data)
    assert masked["email"] != data["email"]
    assert masked["tel"] == "***"
