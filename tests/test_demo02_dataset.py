"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verify natural-language requests, unchanged offers and source labels.
"""

from collections import Counter
from copy import deepcopy
from datetime import date
import hashlib
import json
import re

import pytest

from agent_evals.generate_demo02_dataset import ROOT, transform_cases, write_dataset
from agent_evals.selection import select_best_offer

SOURCE = ROOT / "data/datasets/express-order-v1.json"
TARGET = ROOT / "data/datasets/demo02-express-order-v1.json"
RULES = ROOT / "rules/offer-selection.md"
MONTH_NAMES = "January February March April May June July August September October November December".split()
MONTH_PATTERN = "(?:" + "|".join(MONTH_NAMES) + ")"
DATE_PATTERN = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}} {MONTH_PATTERN} \d{{4}}|{MONTH_PATTERN} \d{{1,2}}, \d{{4}})\b"
)


def _recover_date(text: str) -> str:
    """Recover one date independently of the generator's formatting functions.

    Args:
        text: ISO date or a spelled-out English calendar date.

    Returns:
        The corresponding ISO calendar date.
    """
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text).isoformat()
    tokens = text.replace(",", "").split()
    if tokens[0].isdigit():
        day, month, year = tokens
    else:
        month, day, year = tokens
    return date(int(year), MONTH_NAMES.index(month) + 1, int(day)).isoformat()


def _recover_request(text: str, cities: list[str]) -> dict:
    """Recover only the three requested facts from the English delivery request.

    Args:
        text: English request without any offer descriptions.
        cities: Allowed plant city names from the location catalog.

    Returns:
        Structured part, destination and exclusive deadline for comparison.
    """
    city_pattern = re.compile(r"\b(?:" + "|".join(re.escape(c) for c in cities) + r")\b")
    parts = re.findall(r"\bPART-\d{3}\b", text)
    destinations = city_pattern.findall(text)
    deadlines = DATE_PATTERN.findall(text)
    assert len(parts) == len(destinations) == len(deadlines) == 1
    return {"part_id": parts[0], "delivery_location": destinations[0],
            "latest_delivery_date": _recover_date(deadlines[0])}


def test_all_demo02_facts_order_labels_and_splits_match_source():
    """Verify that only request representation changes across all 100 cases."""
    original = json.loads(SOURCE.read_text())
    derived = json.loads(TARGET.read_text())
    locations = json.loads((ROOT / "data/catalogs/locations.json").read_text())
    assert len(derived) == 100 and len({c["input"]["request"] for c in derived}) == 100
    assert [c["id"] for c in derived] == [c["id"] for c in original]
    for source, demo02 in zip(original, derived):
        assert set(demo02["input"]) == {"request", "offers"}
        text = demo02["input"]["request"]
        assert isinstance(text, str) and not any(character in text for character in "{}[]")
        assert "expected_offer_id" not in text and "expected_output" not in text
        assert demo02["expected_output"] == source["expected_output"]
        assert all(demo02["metadata"][key] == value for key, value in source["metadata"].items())
        assert re.search(r"\b(?:offer|quotation|quote)\b", text, re.IGNORECASE)
        assert not re.search(r"\b(?:SUP-\d{3}|EO-\d{3}-OFF-\d{2}|EUR|euros)\b", text, re.IGNORECASE)
        assert demo02["input"]["offers"] == source["input"]["offers"]
        assert len(demo02["input"]["offers"]) == 6
        recovered = {"request": _recover_request(text, [location["name"] for location in locations]),
                     "offers": demo02["input"]["offers"]}
        assert recovered == source["input"]
        assert select_best_offer(recovered) == source["expected_output"]["expected_offer_id"]
    assert Counter(c["metadata"]["split"] for c in derived) == {"development": 20, "evaluation": 80}
    assert set(Counter(c["metadata"]["request_template"] for c in derived).values()) == {10}
    assert len({c["metadata"]["request_template"] for c in derived}) == 10
    assert {c["metadata"]["request_date_style"] for c in derived} == {
        "iso", "day_month_year", "month_day_year",
    }


def test_demo02_generation_is_reproducible_and_does_not_modify_source(tmp_path):
    """Reproduce stored artifacts and verify their source lineage and seed control."""
    source_bytes = SOURCE.read_bytes()
    source_cases = json.loads(source_bytes)
    snapshot = deepcopy(source_cases)
    assert transform_cases(source_cases) == json.loads(TARGET.read_text())
    assert source_cases == snapshot
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    manifest = write_dataset(SOURCE, first, RULES)
    assert write_dataset(SOURCE, second, RULES) == manifest
    assert first.read_bytes() == second.read_bytes() == TARGET.read_bytes()
    assert first.with_suffix(".manifest.json").read_bytes() == TARGET.with_suffix(".manifest.json").read_bytes()
    assert manifest["source_sha256"][f"datasets/{SOURCE.name}"] == hashlib.sha256(source_bytes).hexdigest()
    assert manifest["dataset_sha256"] == hashlib.sha256(TARGET.read_bytes()).hexdigest()
    alternate = transform_cases(source_cases, seed=43)
    assert [c["input"] for c in alternate] != [c["input"] for c in transform_cases(source_cases)]
    assert [c["expected_output"] for c in alternate] == [c["expected_output"] for c in source_cases]
    assert SOURCE.read_bytes() == source_bytes


def test_demo02_cannot_overwrite_the_original_dataset():
    """Reject destinations that would overwrite source data or its manifest."""
    with pytest.raises(ValueError, match="must not overwrite"):
        write_dataset(SOURCE, SOURCE, RULES)
