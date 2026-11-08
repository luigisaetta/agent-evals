"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Verify reference selection with hand-authored business-rule cases.
"""

from copy import deepcopy
from itertools import permutations

import pytest

from agent_evals.selection import (
    AmbiguousWinnerError, NoEligibleOfferError, select_best_offer,
)


def _offer(identifier="A", cost=10.01, delivery="2027-03-01", **changes):
    return dict(offer_id=identifier, supplier_id="SUP-001", part_id="PART-001",
                delivery_location="Rome", delivery_date=delivery,
                total_cost_eur=cost) | changes


def _task(*offers):
    return {"request": {"part_id": "PART-001", "delivery_location": "Rome",
                        "latest_delivery_date": "2027-03-10"}, "offers": list(offers)}


@pytest.mark.parametrize("changes", [
    {"part_id": "PART-002"}, {"delivery_location": "Paris"},
    {"delivery_date": "2027-03-10"}, {"delivery_date": "2027-03-11"},
    {"part_id": "part-001"}, {"delivery_location": "rome"},
])
def test_cheaper_ineligible_offer_cannot_win(changes):
    """Require every eligibility condition, including strict deadline equality."""
    assert select_best_offer(_task(_offer(), _offer("B", 1, **changes))) == "A"


def test_cost_precedes_speed_and_decimal_margin():
    """Select the cheaper offer even if it arrives later, across a cent boundary."""
    task = _task(_offer("A", 10.01, "2027-03-01"), _offer("B", 10.00, "2027-03-09"))
    assert select_best_offer(task) == "B"


def test_equal_cost_uses_earliest_date_and_ignores_order():
    """Check all permutations without introducing a supplier preference."""
    offers = [_offer("A", 10, "2027-03-09"), _offer("B", 10, "2027-02-28"),
              _offer("C", 12, "2027-02-01", supplier_id="SUP-002")]
    for ordered in permutations(offers):
        task = _task(*ordered)
        original = deepcopy(task)
        assert select_best_offer(task) == "B"
        assert task == original


def test_no_eligible_offer_and_empty_offers():
    """Distinguish unsupported no-winner cases from malformed empty input."""
    with pytest.raises(NoEligibleOfferError):
        select_best_offer(_task(_offer(delivery="2027-03-10")))
    with pytest.raises(ValueError, match="non-empty array"):
        select_best_offer(_task())


def test_unresolved_tie_and_duplicate_identifiers():
    """Reject ambiguity rather than breaking ties on supplier or input order."""
    with pytest.raises(AmbiguousWinnerError):
        select_best_offer(_task(_offer(), _offer("B", supplier_id="SUP-002")))
    with pytest.raises(ValueError, match="Duplicate offer_id"):
        select_best_offer(_task(_offer(), _offer()))


@pytest.mark.parametrize("bad_cost", [-1, True, "10.00", None, 1.001, float("nan"), float("inf")])
def test_invalid_costs_are_rejected(bad_cost):
    """Reject costs that cannot be valid non-negative two-decimal JSON amounts."""
    with pytest.raises(ValueError, match="total_cost_eur"):
        select_best_offer(_task(_offer(cost=bad_cost)))


@pytest.mark.parametrize("bad_date", ["2027-02-29", "2027-3-01", "2027-03-01T00:00:00", ""])
def test_invalid_dates_are_rejected(bad_date):
    """Validate real dates and the required date-only representation."""
    with pytest.raises(ValueError):
        select_best_offer(_task(_offer(delivery=bad_date)))


def test_missing_supplier_on_ineligible_offer_is_rejected():
    """Validate every offer before filtering, including irrelevant candidates."""
    bad = _offer("B", part_id="OTHER")
    del bad["supplier_id"]
    with pytest.raises(ValueError, match="supplier_id"):
        select_best_offer(_task(_offer(), bad))


def test_valid_zero_cost():
    """Accept a zero-cost offer under the documented non-negative cost contract."""
    assert select_best_offer(_task(_offer(cost=0), _offer("B", 1))) == "A"
