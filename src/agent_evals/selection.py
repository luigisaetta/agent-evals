"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Validate offer-selection inputs and compute the reference winner.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import re


class NoEligibleOfferError(ValueError):
    """Indicate that no offer satisfies the request."""


class AmbiguousWinnerError(ValueError):
    """Indicate that multiple offers share the best cost and delivery date."""


def _text(record: dict, key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string")
    return value


def _date(record: dict, key: str, context: str) -> date:
    value = _text(record, key, context)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"{context}.{key} must use YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{context}.{key} must be a valid calendar date") from error


def _cost(offer: dict, context: str) -> Decimal:
    value = offer.get("total_cost_eur")
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{context}.total_cost_eur must be a JSON number")
    cost = Decimal(str(value))
    if not cost.is_finite() or cost < 0:
        raise ValueError(f"{context}.total_cost_eur must be finite and non-negative")
    try:
        valid_precision = cost == cost.quantize(Decimal("0.01"))
    except InvalidOperation:
        valid_precision = False
    if not valid_precision:
        raise ValueError(f"{context}.total_cost_eur must have at most two decimals")
    return cost


def select_best_offer(task_input: dict) -> str:
    """Return the unique best eligible offer under rules version 1.1.

    Args:
        task_input: Request and offers, without reference outputs or metadata.

    Returns:
        The winning offer identifier.

    Raises:
        ValueError: If the request or any offer violates the input contract.
        NoEligibleOfferError: If no offer is eligible.
        AmbiguousWinnerError: If the best cost and date do not identify one offer.
    """
    if not isinstance(task_input, dict):
        raise ValueError("Task input must be an object")
    request = task_input.get("request")
    offers = task_input.get("offers")
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    part = _text(request, "part_id", "request")
    city = _text(request, "delivery_location", "request")
    deadline = _date(request, "latest_delivery_date", "request")
    if not isinstance(offers, list) or not offers:
        raise ValueError("offers must be a non-empty array")

    identifiers = set()
    eligible = []
    for index, offer in enumerate(offers):
        context = f"offers[{index}]"
        if not isinstance(offer, dict):
            raise ValueError(f"{context} must be an object")
        offer_id = _text(offer, "offer_id", context)
        if offer_id in identifiers:
            raise ValueError(f"Duplicate offer_id: {offer_id}")
        identifiers.add(offer_id)
        _text(offer, "supplier_id", context)
        offer_part = _text(offer, "part_id", context)
        offer_city = _text(offer, "delivery_location", context)
        delivery = _date(offer, "delivery_date", context)
        cost = _cost(offer, context)
        if offer_part == part and offer_city == city and delivery < deadline:
            eligible.append((cost, delivery, offer_id))

    if not eligible:
        raise NoEligibleOfferError("No offer matches the part, city and deadline")
    best_rank = min((cost, delivery) for cost, delivery, _ in eligible)
    winners = [identifier for cost, delivery, identifier in eligible
               if (cost, delivery) == best_rank]
    if len(winners) != 1:
        raise AmbiguousWinnerError(f"Unresolved cost/date tie: {winners}")
    return winners[0]
