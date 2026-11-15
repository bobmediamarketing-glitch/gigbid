"""PII masking for logs, traces and the audit log (R9 / E4)."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card]"),                       # payment card numbers
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), "[iban]"),
    (re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)"), "[phone]"),
    (re.compile(r"(?i)\b(bearer\s+)[\w.-]{8,}"), r"\1[token]"),
    (re.compile(r"(?<![\w.])@[A-Za-z0-9_]{4,}\b"), "[handle]"),             # messaging handles
]
_SECRET_KEYS = {"token", "access_token", "refresh_token", "authorization", "password", "secret", "api_key"}


def mask_text(s: str) -> str:
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s


def mask(obj: Any) -> Any:
    """Recursively mask strings; drop values of secret-looking keys entirely."""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: ("[redacted]" if k.lower() in _SECRET_KEYS else mask(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask(v) for v in obj]
    return obj
