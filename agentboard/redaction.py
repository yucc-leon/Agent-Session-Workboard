"""Redaction utilities — strip secrets from text before it goes to an LLM."""

import re

# ---------------------------------------------------------------------------
# Secret patterns (regex)
# ---------------------------------------------------------------------------
SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_SECRET]"),
    (r"ghp_[A-Za-z0-9_]{20,}", "[REDACTED_SECRET]"),
    (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        r'(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[\'"]?[^\'"\s]+',
        r"\1=[REDACTED_SECRET]",
    ),
    (
        r'(?i)Bearer\s+[A-Za-z0-9_\-\.]{20,}',
        "Bearer [REDACTED_TOKEN]",
    ),
    (r'(?i)x-api-key\s*[:=]\s*[^\s\'"]+', "x-api-key=[REDACTED]"),
]

# ---------------------------------------------------------------------------
# Text / dict redaction
# ---------------------------------------------------------------------------

def redact_text(text: str) -> str:
    """Apply secret redaction patterns to a string."""
    if not text:
        return text
    for pattern, replacement in SECRET_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text


def redact_dict(obj: dict) -> dict:
    """Recursively redact secrets in a dict."""
    if not obj:
        return obj
    result = {}
    for k, v in obj.items():
        if isinstance(v, str):
            result[k] = redact_text(v)
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [
                redact_dict(item) if isinstance(item, dict)
                else redact_text(item) if isinstance(item, str)
                else item
                for item in v
            ]
        else:
            result[k] = v
    return result
