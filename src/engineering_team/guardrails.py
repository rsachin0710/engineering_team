"""Local input guardrails, run before any user text is sent to an LLM.

Detection is deliberately pattern-based and runs entirely in-process: asking an
LLM whether text contains PII would itself leak that PII to the provider.
"""
import ipaddress
import re

PII_MESSAGE = (
    "Your requirements appear to contain personal information (PII). "
    "Please remove any PII and try again."
)

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_US_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_INDIA_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_DATE_OF_BIRTH = re.compile(r"\b(?:dob|d\.o\.b\.?|date of birth|born on)\b\s*[:\-]?\s*\d", re.IGNORECASE)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# A run of digits optionally broken up by spaces, dashes, dots or brackets,
# e.g. "+1 (555) 123-4567", "4111 1111 1111 1111", "1234 5678 9012".
_DIGIT_RUN = re.compile(r"(?<![\w.])\+?\(?\d[\d \-().]{7,}\d(?![\w])")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _classify_digit_run(run: str) -> str | None:
    digits = re.sub(r"\D", "", run)
    formatted = run.startswith("+") or bool(re.search(r"[ \-().]", run))
    if 13 <= len(digits) <= 19 and _luhn_valid(digits):
        return "payment card number"
    if len(digits) == 12 and (formatted or digits[0] not in "01"):
        return "national ID number"  # e.g. Aadhaar
    if 10 <= len(digits) <= 15:
        # Unformatted 10-digit numbers are only flagged when they look like an
        # Indian mobile number, so plain amounts like 1000000000 pass.
        if formatted or re.fullmatch(r"[6-9]\d{9}", digits):
            return "phone number"
    return None


def find_pii(text: str) -> list[str]:
    """Return the kinds of PII detected in `text` (empty list if none)."""
    found: list[str] = []
    if _EMAIL.search(text):
        found.append("email address")
    if _US_SSN.search(text):
        found.append("social security number")
    if _INDIA_PAN.search(text):
        found.append("PAN number")
    if _IBAN.search(text):
        found.append("bank account number")
    if _DATE_OF_BIRTH.search(text):
        found.append("date of birth")
    for match in _IPV4.findall(text):
        try:
            if ipaddress.ip_address(match).is_global:
                found.append("IP address")
                break
        except ValueError:
            continue
    for match in _DIGIT_RUN.findall(text):
        kind = _classify_digit_run(match.strip())
        if kind and kind not in found:
            found.append(kind)
    return found


def contains_pii(text: str) -> bool:
    return bool(find_pii(text))
