import re

SENSITIVE_PATTERNS = (
    re.compile(r"\b(?:sk|pk)_(?:test|live)_[A-Za-z0-9_-]+\b"),
    re.compile(r"\b(?:token|dynamic_cvv|cvv|cryptogram)\s*[:=]\s*[^\s,]+", re.IGNORECASE),
)


def redact_sensitive(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


class RedactingLogFilter:
    def filter(self, record) -> bool:  # type: ignore[no-untyped-def]
        record.msg = redact_sensitive(record.getMessage())
        record.args = ()
        return True
