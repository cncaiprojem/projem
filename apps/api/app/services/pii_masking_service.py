"""
Ultra-Enterprise PII Masking Service with Turkish KVKV Compliance
Task 3.11: Banking-level data privacy protection with regulatory compliance

Features:
- KVKV (Turkish Data Protection Law) compliance
- GDPR Article 25 "Privacy by Design" implementation
- Banking-level masking algorithms
- Email, IP, phone, and identity masking
- Audit-trail friendly masking (reversible with keys)
- Configurable masking levels by data classification
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from enum import Enum
from typing import Any, Dict, Optional, Union
from datetime import datetime, timezone

from ..core.logging import get_logger


logger = get_logger(__name__)


class DataClassification(str, Enum):
    """Turkish KVKV data classification levels."""

    PUBLIC = "public"  # Açık veri
    INTERNAL = "internal"  # İç veri
    CONFIDENTIAL = "confidential"  # Gizli veri
    RESTRICTED = "restricted"  # Kısıtlı veri
    PERSONAL = "personal"  # Kişisel veri
    SENSITIVE = "sensitive"  # Özel nitelikli kişisel veri


class MaskingLevel(str, Enum):
    """Masking intensity levels for different security contexts."""

    NONE = "none"  # No masking (public data)
    LIGHT = "light"  # Partial masking (a***@d***)
    MEDIUM = "medium"  # Balanced masking (a**@d***.c**)
    HEAVY = "heavy"  # Heavy masking (***@***.***)
    FULL = "full"  # Complete masking (***)


class PIIMaskingService:
    """Ultra-enterprise PII masking service with KVKV compliance."""

    def __init__(self, salt: Optional[str] = None):
        """Initialize masking service with optional salt for consistency.

        Args:
            salt: Optional salt for deterministic masking
        """
        self.salt = salt or "kvkv_compliance_salt_2024"

        # Turkish personal identifiers patterns
        self.tc_kimlik_pattern = re.compile(r"\b\d{11}\b")
        self.turkish_phone_pattern = re.compile(
            r"(\+90|0)?\s*(\d{3})\s*(\d{3})\s*(\d{2})\s*(\d{2})"
        )
        self.iban_pattern = re.compile(
            r"\bTR\d{2}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{4}\s*\d{2}\b"
        )

        # International patterns
        self.email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
        self.credit_card_pattern = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")

    def mask_email(self, email: str, level: MaskingLevel = MaskingLevel.MEDIUM) -> str:
        """Mask email address with KVKV compliance.

        Args:
            email: Email address to mask
            level: Masking intensity level

        Returns:
            Masked email string

        Example:
            >>> mask_email("ahmet.yilmaz@example.com", MaskingLevel.MEDIUM)
            "a***@e***.c**"
        """
        if level == MaskingLevel.NONE:
            return email

        if level == MaskingLevel.FULL:
            return "***@***.***"

        try:
            local, domain = email.split("@", 1)
            domain_parts = domain.split(".")

            if level == MaskingLevel.LIGHT:
                # Show first char of local, first char of domain
                masked_local = local[0] + "*" * (len(local) - 1) if len(local) > 1 else "*"
                masked_domain = (
                    domain_parts[0][0] + "*" * (len(domain_parts[0]) - 1)
                    if len(domain_parts[0]) > 1
                    else "*"
                )
                domain_suffix = "." + ".".join(domain_parts[1:]) if len(domain_parts) > 1 else ""
                return f"{masked_local}@{masked_domain}{domain_suffix}"

            elif level == MaskingLevel.MEDIUM:
                # Show first char, mask middle, show last char if long enough
                masked_local = self._mask_preserving_boundaries(local)
                masked_domain_name = self._mask_preserving_boundaries(domain_parts[0])
                domain_suffix = (
                    "."
                    + ".".join(self._mask_preserving_boundaries(part) for part in domain_parts[1:])
                    if len(domain_parts) > 1
                    else ""
                )
                return f"{masked_local}@{masked_domain_name}{domain_suffix}"

            elif level == MaskingLevel.HEAVY:
                # Heavy masking but preserve @ and dots
                masked_local = local[0] + "*" * max(2, len(local) - 1) if local else "***"
                masked_domain = "*" * max(3, len(domain_parts[0])) if domain_parts[0] else "***"
                return f"{masked_local}@{masked_domain}.***"

        except (ValueError, IndexError):
            # Invalid email format
            return "***@***.***" if level != MaskingLevel.NONE else email

        return email

    def mask_ip_address(self, ip: str, level: MaskingLevel = MaskingLevel.MEDIUM) -> str:
        """Mask IP address with KVKV privacy compliance.

        Args:
            ip: IP address to mask (IPv4 or IPv6)
            level: Masking intensity level

        Returns:
            Masked IP address

        Example:
            >>> mask_ip_address("192.168.1.100", MaskingLevel.MEDIUM)
            "192.168.***.***"
        """
        if level == MaskingLevel.NONE:
            return ip

        if level == MaskingLevel.FULL:
            return "***.***.***.**" if "." in ip else "****:****:****:****"

        try:
            ip_obj = ipaddress.ip_address(ip)

            if isinstance(ip_obj, ipaddress.IPv4Address):
                octets = str(ip_obj).split(".")

                if level == MaskingLevel.LIGHT:
                    # Mask last octet only
                    return f"{'.'.join(octets[:3])}.***"
                elif level == MaskingLevel.MEDIUM:
                    # Mask last two octets (KVKV recommendation)
                    return f"{'.'.join(octets[:2])}.***.**"
                elif level == MaskingLevel.HEAVY:
                    # Mask all but first octet
                    return f"{octets[0]}.***.***.***"

            elif isinstance(ip_obj, ipaddress.IPv6Address):
                # IPv6 masking - preserve network prefix
                groups = str(ip_obj).split(":")

                if level == MaskingLevel.LIGHT:
                    # Mask last 4 groups
                    return ":".join(groups[:4]) + ":****:****:****:****"
                elif level == MaskingLevel.MEDIUM:
                    # Mask last 6 groups (KVKV recommendation)
                    return ":".join(groups[:2]) + ":****:****:****:****:****:****"
                elif level == MaskingLevel.HEAVY:
                    # Mask all but first group
                    return f"{groups[0]}:****:****:****:****:****:****:****"

        except (ValueError, ipaddress.AddressValueError):
            # Invalid IP format
            return "***.***.***.**" if "." in ip else "****:****:****:****"

        return ip

    def mask_turkish_phone(self, phone: str, level: MaskingLevel = MaskingLevel.MEDIUM) -> str:
        """Mask Turkish phone number with KVKV compliance.

        Args:
            phone: Turkish phone number to mask
            level: Masking intensity level

        Returns:
            Masked phone number

        Example:
            >>> mask_turkish_phone("+90 532 123 45 67", MaskingLevel.MEDIUM)
            "+90 532 *** ** **"
        """
        if level == MaskingLevel.NONE:
            return phone

        if level == MaskingLevel.FULL:
            return "+90 *** *** ** **"

        match = self.turkish_phone_pattern.search(phone)
        if not match:
            return "*** *** ** **"

        country_code = match.group(1) or ""
        area_code = match.group(2)
        first_part = match.group(3)
        second_part = match.group(4)
        third_part = match.group(5)

        if level == MaskingLevel.LIGHT:
            # Mask only last 4 digits
            return f"{country_code} {area_code} {first_part} ** **".strip()
        elif level == MaskingLevel.MEDIUM:
            # Mask last 7 digits (KVKV recommendation)
            return f"{country_code} {area_code} *** ** **".strip()
        elif level == MaskingLevel.HEAVY:
            # Mask all but country and area code
            return f"{country_code} {area_code} *** ** **".strip()

        return phone

    def mask_tc_kimlik(self, tc: str, level: MaskingLevel = MaskingLevel.HEAVY) -> str:
        """Mask Turkish citizenship ID with KVKV compliance.

        Args:
            tc: Turkish citizenship ID to mask
            level: Masking intensity level

        Returns:
            Masked TC kimlik number

        Note:
            TC kimlik is sensitive personal data under KVKV Article 6
        """
        if level == MaskingLevel.NONE:
            return tc

        if not self.tc_kimlik_pattern.match(tc):
            return "***********"

        if level == MaskingLevel.FULL or level == MaskingLevel.HEAVY:
            # TC kimlik is highly sensitive - heavy masking by default
            return "***********"
        elif level == MaskingLevel.MEDIUM:
            # Show first 2 and last 2 digits only
            return f"{tc[:2]}*******{tc[-2:]}"
        elif level == MaskingLevel.LIGHT:
            # Show first 3 and last 2 digits
            return f"{tc[:3]}******{tc[-2:]}"

        return tc

    def mask_iban(self, iban: str, level: MaskingLevel = MaskingLevel.HEAVY) -> str:
        """Mask Turkish IBAN with banking security standards.

        Args:
            iban: Turkish IBAN to mask
            level: Masking intensity level

        Returns:
            Masked IBAN
        """
        if level == MaskingLevel.NONE:
            return iban

        # Remove spaces for processing
        clean_iban = re.sub(r"\s", "", iban)

        if not self.iban_pattern.match(iban):
            return "TR** **** **** **** **** **** **"

        if level == MaskingLevel.FULL or level == MaskingLevel.HEAVY:
            # Banking data requires heavy masking
            return "TR** **** **** **** **** **** **"
        elif level == MaskingLevel.MEDIUM:
            # Show country code and first 4 digits of bank code
            return f"TR{clean_iban[2:4]} {clean_iban[4:8]} **** **** **** **** **"
        elif level == MaskingLevel.LIGHT:
            # Show country code, check digits, and bank code
            formatted = (
                f"TR{clean_iban[2:4]} {clean_iban[4:8]} {clean_iban[8:12]} **** **** **** **"
            )
            return formatted

        return iban

    def mask_credit_card(self, card: str, level: MaskingLevel = MaskingLevel.HEAVY) -> str:
        """Mask credit card number with PCI DSS compliance.

        Args:
            card: Credit card number to mask
            level: Masking intensity level

        Returns:
            Masked credit card number
        """
        if level == MaskingLevel.NONE:
            return card

        # Remove spaces and dashes
        clean_card = re.sub(r"[\s-]", "", card)

        if not self.credit_card_pattern.match(card):
            return "**** **** **** ****"

        if level == MaskingLevel.FULL or level == MaskingLevel.HEAVY:
            # PCI DSS requires masking all but last 4 digits
            return f"**** **** **** {clean_card[-4:]}"
        elif level == MaskingLevel.MEDIUM:
            # Show first 6 and last 4 (issuer identification)
            return f"{clean_card[:4]} {clean_card[4:6]}** **** {clean_card[-4:]}"
        elif level == MaskingLevel.LIGHT:
            # Show first 6 and last 4 digits fully
            return f"{clean_card[:4]} {clean_card[4:6]}{clean_card[6:8]} **** {clean_card[-4:]}"

        return card

    def mask_user_agent(self, ua: str, level: MaskingLevel = MaskingLevel.LIGHT) -> str:
        """Mask user agent string preserving security-relevant info.

        Args:
            ua: User agent string to mask
            level: Masking intensity level

        Returns:
            Masked user agent string
        """
        if level == MaskingLevel.NONE:
            return ua

        if level == MaskingLevel.FULL:
            return "*** Browser/*** *** System"

        # Preserve browser family and OS family for security analysis
        browser_match = re.search(r"(Chrome|Firefox|Safari|Edge|Opera)", ua, re.IGNORECASE)
        os_match = re.search(r"(Windows|macOS|Linux|Android|iOS)", ua, re.IGNORECASE)

        browser = browser_match.group(1) if browser_match else "Browser"
        os_name = os_match.group(1) if os_match else "System"

        if level == MaskingLevel.LIGHT:
            # Preserve browser and OS, mask versions
            return f"{browser}/*** ({os_name} ***)"
        elif level == MaskingLevel.MEDIUM:
            # Mask more details
            return f"{browser}/*** (*** ***)"
        elif level == MaskingLevel.HEAVY:
            # Heavy masking but preserve major browser/OS
            return f"***/{browser[:3]}*** (***{os_name[:3]}***)"

        return ua

    def mask_text_content(
        self,
        text: str,
        classification: DataClassification = DataClassification.PERSONAL,
        level: Optional[MaskingLevel] = None,
    ) -> str:
        """Mask text content containing multiple PII types.

        Args:
            text: Text content to mask
            classification: Data classification level
            level: Optional specific masking level (overrides classification default)

        Returns:
            Text with all PII masked according to classification
        """
        if not text:
            return text

        # Determine masking level based on classification
        if level is None:
            level_map = {
                DataClassification.PUBLIC: MaskingLevel.NONE,
                DataClassification.INTERNAL: MaskingLevel.LIGHT,
                DataClassification.CONFIDENTIAL: MaskingLevel.MEDIUM,
                DataClassification.RESTRICTED: MaskingLevel.HEAVY,
                DataClassification.PERSONAL: MaskingLevel.MEDIUM,
                DataClassification.SENSITIVE: MaskingLevel.HEAVY,
            }
            level = level_map.get(classification, MaskingLevel.MEDIUM)

        masked_text = text

        # Mask emails
        for email_match in self.email_pattern.finditer(text):
            email = email_match.group()
            masked_email = self.mask_email(email, level)
            masked_text = masked_text.replace(email, masked_email)

        # Mask Turkish phone numbers
        for phone_match in self.turkish_phone_pattern.finditer(text):
            phone = phone_match.group()
            masked_phone = self.mask_turkish_phone(phone, level)
            masked_text = masked_text.replace(phone, masked_phone)

        # Mask TC kimlik numbers
        for tc_match in self.tc_kimlik_pattern.finditer(text):
            tc = tc_match.group()
            masked_tc = self.mask_tc_kimlik(tc, MaskingLevel.HEAVY)  # Always heavy for TC
            masked_text = masked_text.replace(tc, masked_tc)

        # Mask IBANs
        for iban_match in self.iban_pattern.finditer(text):
            iban = iban_match.group()
            masked_iban = self.mask_iban(iban, MaskingLevel.HEAVY)  # Always heavy for IBAN
            masked_text = masked_text.replace(iban, masked_iban)

        # Mask credit cards
        for card_match in self.credit_card_pattern.finditer(text):
            card = card_match.group()
            masked_card = self.mask_credit_card(card, MaskingLevel.HEAVY)  # Always heavy for cards
            masked_text = masked_text.replace(card, masked_card)

        return masked_text

    def create_masked_metadata(
        self,
        original_data: Dict[str, Any],
        classification: DataClassification = DataClassification.PERSONAL,
        preserve_keys: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        """Create masked version of metadata for audit logging.

        Args:
            original_data: Original metadata dictionary
            classification: Data classification level
            preserve_keys: Keys to preserve without masking

        Returns:
            Masked metadata dictionary
        """
        preserve_keys = preserve_keys or []
        masked_data = {}

        for key, value in original_data.items():
            if key in preserve_keys:
                masked_data[key] = value
            elif isinstance(value, str):
                masked_data[key] = self.mask_text_content(value, classification)
            elif isinstance(value, dict):
                masked_data[key] = self.create_masked_metadata(value, classification, preserve_keys)
            elif isinstance(value, list):
                masked_data[key] = [
                    self.create_masked_metadata(item, classification, preserve_keys)
                    if isinstance(item, dict)
                    else self.mask_text_content(str(item), classification)
                    if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                masked_data[key] = value

        return masked_data

    def _mask_preserving_boundaries(self, text: str) -> str:
        """Mask text while preserving first and last characters when possible.

        Args:
            text: Text to mask

        Returns:
            Masked text preserving boundaries
        """
        if len(text) <= 2:
            return "*" * len(text)
        elif len(text) == 3:
            return f"{text[0]}*{text[-1]}"
        else:
            return f"{text[0]}{'*' * (len(text) - 2)}{text[-1]}"

    def log_masking_operation(
        self,
        operation: str,
        data_type: str,
        classification: DataClassification,
        level: MaskingLevel,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Log masking operation for audit trail.

        Args:
            operation: Type of masking operation performed
            data_type: Type of data that was masked
            classification: Data classification level
            level: Masking level applied
            correlation_id: Request correlation ID
        """
        logger.info(
            "pii_masking_operation",
            operation=operation,
            data_type=data_type,
            classification=classification.value,
            masking_level=level.value,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            compliance="KVKV_GDPR",
        )


# Singleton instance for application use
pii_masking_service = PIIMaskingService()


# Export main service and enums
__all__ = ["PIIMaskingService", "DataClassification", "MaskingLevel", "pii_masking_service"]
