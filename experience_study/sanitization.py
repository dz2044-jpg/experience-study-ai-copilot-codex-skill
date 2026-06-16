"""Shared sanitization helpers for aggregate A/E artifacts."""

from __future__ import annotations

import re
from typing import Any

MASKED_COHORT_LABEL = "[masked cohort label]"
MASKED_DIMENSION_COLUMN = "[masked dimension]"
MASKED_FILTER_COLUMN = "[masked column]"
MASKED_FILTER_VALUE = "[masked value]"

SENSITIVE_DIMENSION_TERMS = {
    "policy",
    "policy_number",
    "name",
    "dob",
    "birth",
    "ssn",
    "email",
    "phone",
    "address",
    "zip",
    "postal",
    "member",
    "applicant",
    "insured",
    "id",
    "number",
    "account",
    "certificate",
}

_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[\d\s().-]{7,}$")
_SSN_RE = re.compile(r"^\d{3}-?\d{2}-?\d{4}$")


def _dimension_tokens(column: str) -> set[str]:
    expanded = _CAMEL_BOUNDARY_RE.sub("_", column)
    tokens = [token.lower() for token in re.split(r"[^A-Za-z0-9]+", expanded) if token]
    token_set = set(tokens)
    if tokens:
        token_set.add("_".join(tokens))
    return token_set


def dimension_column_is_sensitive(column: str) -> bool:
    """Return whether a cohort dimension column should be masked."""

    return bool(_dimension_tokens(column) & SENSITIVE_DIMENSION_TERMS)


def parse_dimension_label(dimensions: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Parse an aggregate `Dimensions` label into column/value pairs."""

    parsed: list[tuple[str, str]] = []
    warnings: list[str] = []
    for part in str(dimensions).split(" | "):
        if "=" not in part:
            warnings.append("dimension_parse_warning")
            continue
        column, value = part.split("=", 1)
        column = column.strip()
        value = value.strip()
        if not column:
            warnings.append("dimension_parse_warning")
            continue
        parsed.append((column, value))
    return parsed, warnings


def value_looks_sensitive(value: Any) -> bool:
    """Return whether a scalar value resembles sensitive personal data."""

    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return bool(_EMAIL_RE.match(stripped) or _PHONE_RE.match(stripped) or _SSN_RE.match(stripped))


def sanitize_filters(filters: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Mask sensitive filter columns or values in aggregate metadata."""

    sanitized: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for filter_spec in filters or []:
        column = str(filter_spec.get("column", ""))
        value = filter_spec.get("value")
        operator = filter_spec.get("operator", filter_spec.get("op"))
        if dimension_column_is_sensitive(column) or value_looks_sensitive(value):
            sanitized.append({"column": MASKED_FILTER_COLUMN, "operator": operator, "value": MASKED_FILTER_VALUE})
            warnings.append({"code": "sensitive_filter_masked", "message": "A sensitive or disallowed filter was masked."})
        else:
            sanitized.append({"column": column, "operator": operator, "value": value})
    return sanitized, warnings
