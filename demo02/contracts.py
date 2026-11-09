"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Validate Demo02 inputs and the extracted structured delivery request.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import json
import re

from agent_evals.tasks.offer_selection import validate_offers


def _iso_date(value: object) -> str:
    """Validate an exact ISO calendar date.

    Args:
        value: Candidate date value.

    Returns:
        The unchanged YYYY-MM-DD date.

    Raises:
        ValueError: If the value is not a valid ISO calendar date.
    """
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Date must be a YYYY-MM-DD string")
    date.fromisoformat(value)
    return value


def validate_agent_input(request: str, offers: list[dict]) -> None:
    """Validate an NL request and six offers before making any model calls.

    Args:
        request: Natural-language delivery requirement.
        offers: Original structured supplier offers.

    Raises:
        ValueError: If the request or an offer violates the input contract.
    """
    if not isinstance(request, str) or not request.strip():
        raise ValueError("Request must be a non-empty English string")
    validate_offers(offers)
    for offer in offers:
        for field in ("supplier_id", "part_id", "delivery_location"):
            if not isinstance(offer[field], str) or not offer[field].strip():
                raise ValueError(f"Offer {field} must be a non-empty string")
        _iso_date(offer["delivery_date"])
        amount = offer["total_cost_eur"]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise ValueError("Offer cost must be a JSON number")
        cost = Decimal(str(amount))
        if not cost.is_finite() or cost < 0:
            raise ValueError("Offer cost must be finite and non-negative")
        try:
            precise = cost == cost.quantize(Decimal("0.01"))
        except InvalidOperation:
            precise = False
        if not precise:
            raise ValueError("Offer cost must have at most two decimal places")


def _unique_fields(pairs: list[tuple]) -> dict:
    """Reject duplicate fields in extracted JSON.

    Args:
        pairs: Decoded object key/value pairs.

    Returns:
        An object with unique field names.

    Raises:
        ValueError: If a field name is repeated.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate extracted request field")
        result[key] = value
    return result


def parse_request(raw_output: str) -> dict:
    """Parse the first model's output into the original request schema.

    Args:
        raw_output: Model response containing only a JSON object.

    Returns:
        Validated part_id, delivery_location and latest_delivery_date fields.

    Raises:
        ValueError: If JSON, fields, types or the date are invalid.
    """
    if not isinstance(raw_output, str):
        raise ValueError("Extraction output must be JSON text")
    request = json.loads(raw_output, object_pairs_hook=_unique_fields)
    if not isinstance(request, dict) or set(request) != {
        "part_id", "delivery_location", "latest_delivery_date",
    }:
        raise ValueError("Extraction must contain exactly the three request fields")
    if any(not isinstance(value, str) or not value.strip() for value in request.values()):
        raise ValueError("Extracted request fields must be non-empty strings")
    _iso_date(request["latest_delivery_date"])
    return request
