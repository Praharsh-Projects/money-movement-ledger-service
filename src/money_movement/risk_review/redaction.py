from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SWEDISH_PERSONAL_ID = re.compile(r"(?<!\d)(?:19|20)?\d{6}[-+]?\d{4}(?!\d)")
_LONG_NUMBER = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){8,15}(?!\w)")
_PAYMENT_CARD = re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")


def redact_text(value: str) -> str:
    """Remove common direct identifiers before text reaches a model or trace."""

    redacted = _EMAIL.sub("[REDACTED_EMAIL]", value)
    redacted = _SWEDISH_PERSONAL_ID.sub("[REDACTED_ID]", redacted)
    redacted = _PAYMENT_CARD.sub("[REDACTED_PAYMENT_CARD]", redacted)
    redacted = _LONG_NUMBER.sub("[REDACTED_NUMBER]", redacted)
    return redacted[:500]


def contains_direct_identifier(value: str) -> bool:
    return any(
        pattern.search(value) for pattern in (_EMAIL, _SWEDISH_PERSONAL_ID, _PAYMENT_CARD, _LONG_NUMBER)
    )
