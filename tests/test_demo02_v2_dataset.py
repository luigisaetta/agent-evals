"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verify Demo02 v2 difficulty levels, unchanged labels and the naive-extractor baseline.
"""

from collections import Counter, defaultdict
from datetime import date, timedelta
import json
import re

import pytest

from agent_evals.dataset import load_cases
from agent_evals.generate_demo02_v2_dataset import ROOT, write_dataset
from demo02.evaluation import TASK as DEMO02_TASK
from agent_evals.selection import select_best_offer

SOURCE = ROOT / "data/datasets/express-order-v1.json"
TARGET = ROOT / "data/datasets/demo02-express-order-v2.json"
RULES = ROOT / "rules/offer-selection.md"
CITIES = [loc["name"] for loc in json.loads((ROOT / "data/catalogs/locations.json").read_text())]
MONTHS = "January February March April May June July August September October November December".split()
MONTH = "(?:" + "|".join(MONTHS) + ")"
DATE_PATTERN = re.compile(rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}} {MONTH} \d{{4}}|{MONTH} \d{{1,2}}, \d{{4}})")
NAIVE_CEILING = 0.20


def _to_iso(text: str) -> str:
    """Convert one of the three supported English date styles to ISO format."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text
    tokens = text.replace(",", "").split()
    day, month, year = tokens if tokens[0].isdigit() else (tokens[1], tokens[0], tokens[2])
    return date(int(year), MONTHS.index(month) + 1, int(day)).isoformat()


def _dates_in(text: str) -> list[str]:
    """Return every calendar date written in the text, in order of appearance."""
    return [_to_iso(match) for match in DATE_PATTERN.findall(text)]


def _nth_business_day_after(anchor: date, count: int) -> date:
    """Count Monday-Friday days forward, starting the day after the anchor."""
    day = anchor
    while count:
        day += timedelta(days=1)
        if day.weekday() < 5:
            count -= 1
    return day


def _exclusive_deadline(spec: dict) -> str:
    """Recompute the exclusive deadline from the recorded deadline specification.

    This follows the phrasing semantics of the specification and deliberately
    does not reuse generator code.
    """
    one = timedelta(days=1)
    form = spec["form"]
    if form == "exclusive":
        result = date.fromisoformat(spec["stated"])
    elif form == "inclusive":
        result = date.fromisoformat(spec["stated"]) + one
    elif form == "relative_days":
        result = date.fromisoformat(spec["anchor"]) + timedelta(days=spec["days"]) + one
    elif form == "relative_weeks":
        result = date.fromisoformat(spec["anchor"]) + timedelta(weeks=spec["weeks"], days=spec["days"]) + one
    elif form == "business_days":
        result = _nth_business_day_after(date.fromisoformat(spec["anchor"]), spec["business_days"]) + one
    elif form == "days_before_event":
        result = date.fromisoformat(spec["event"]) - timedelta(days=spec["days"]) + one
    elif form == "moved_deadline":
        sign = -1 if spec["direction"] == "earlier" else 1
        result = date.fromisoformat(spec["original"]) + sign * timedelta(days=spec["shift_days"])
    else:
        raise AssertionError(f"Unknown deadline form {form}")
    return result.isoformat()


def _naive_extract(text: str) -> dict:
    """Extract like a regex baseline: first canonical part, first city, first date."""
    parts = re.findall(r"\bPART-\d{3}\b", text)
    cities = re.findall(r"\b(?:" + "|".join(map(re.escape, CITIES)) + r")\b", text)
    dates = _dates_in(text)
    return {"part_id": parts[0] if parts else None,
            "delivery_location": cities[0] if cities else None,
            "latest_delivery_date": dates[0] if dates else None}


@pytest.fixture(scope="module", name="derived")
def fixture_derived() -> list[dict]:
    """Load the stored Demo02 v2 dataset."""
    return json.loads(TARGET.read_text())


def test_records_preserve_offers_labels_and_splits(derived):
    """Every level keeps the source offers, label, scenario and split."""
    source = {case["id"]: case for case in json.loads(SOURCE.read_text())}
    assert len(derived) == 300 and len({c["id"] for c in derived}) == 300
    assert Counter(c["metadata"]["level"] for c in derived) == {"L0": 100, "L1": 100, "L2": 100}
    assert Counter(c["metadata"]["split"] for c in derived) == {"development": 60, "evaluation": 240}
    for case in derived:
        original = source[case["metadata"]["source_case_id"]]
        assert case["id"] == f"{original['id']}-{case['metadata']['level']}"
        assert set(case["input"]) == {"request", "offers"}
        assert case["input"]["offers"] == original["input"]["offers"]
        assert case["expected_output"] == {
            "expected_offer_id": original["expected_output"]["expected_offer_id"],
            "expected_request": original["input"]["request"],
        }
        assert all(case["metadata"][key] == value
                   for key, value in original["metadata"].items() if key != "dataset_version")
        assert case["metadata"]["dataset_version"] == "2.0"
        assert case["metadata"]["source_dataset_version"] == original["metadata"]["dataset_version"]
        recovered = {"request": case["expected_output"]["expected_request"], "offers": case["input"]["offers"]}
        assert select_best_offer(recovered) == case["expected_output"]["expected_offer_id"]


def test_dataset_passes_the_shared_loader_with_the_demo02_adapter():
    """The shared loader accepts the dataset, including manifest and version checks."""
    assert len(load_cases(TARGET, RULES, "all", None, DEMO02_TASK)) == 300


def test_l0_reuses_the_v1_requests(derived):
    """L0 is the unchanged v1 request text, so it pairs with the v1 results."""
    v1 = {c["id"]: c["input"]["request"]
          for c in json.loads((ROOT / "data/datasets/demo02-express-order-v1.json").read_text())}
    for case in derived:
        if case["metadata"]["level"] == "L0":
            assert case["input"]["request"] == v1[case["metadata"]["source_case_id"]]


def test_request_facts_imply_the_reference_and_appear_in_text(derived):
    """The recorded facts reproduce the reference, and the text states exactly those facts."""
    for case in derived:
        text, facts = case["input"]["request"], case["metadata"]["request_facts"]
        expected = case["expected_output"]["expected_request"]
        assert _exclusive_deadline(facts["deadline"]) == expected["latest_delivery_date"]
        assert set(_dates_in(text)) == {*facts["key_dates"], *facts["other_dates"]}
        assert expected["latest_delivery_date"] not in facts["other_dates"]
        if facts["deadline"]["form"] not in {"exclusive", "inclusive"}:
            assert expected["latest_delivery_date"] not in _dates_in(text)
        digits = expected["part_id"].split("-")[1]
        surface = {"canonical": f"part PART-{digits}", "part_number": f"part number {digits}",
                   "p_n": f"P/N PART {digits}", "compact": f"part PART{digits}",
                   "part_no": f"part no. {int(digits)}"}[facts["part_form"]]
        assert re.search(rf"{re.escape(surface)}(?!\d)", text)
        assert expected["delivery_location"] in text
        if facts["distractor_part"]:
            assert facts["distractor_part"] in text and facts["distractor_part"] != expected["part_id"]
        if facts["distractor_city"]:
            assert facts["distractor_city"] in text
            assert facts["distractor_city"] != expected["delivery_location"]
        assert not re.search(r"\b(?:SUP-\d{3}|EO-\d{3}-OFF-\d{2}|EUR|euros?|expected_\w+)\b", text, re.I)
        assert not re.search(r"\d+\.\d{2}\b", text)


def test_level_composition(derived):
    """L1 mixes inclusive and relative-days deadlines; every L2 deadline needs arithmetic."""
    forms = defaultdict(Counter)
    l1_forms_by_scenario = defaultdict(set)
    directions = set()
    for case in derived:
        facts, level = case["metadata"]["request_facts"], case["metadata"]["level"]
        form = facts["deadline"]["form"]
        forms[level][form] += 1
        if level == "L1":
            assert facts["part_form"] != "canonical" and facts["distractor_part"]
            l1_forms_by_scenario[case["metadata"]["scenario"]].add(form)
        if level == "L2":
            assert facts["distractor_city"] and case["input"]["request"].startswith("Date: ")
            directions.add(facts["deadline"].get("direction"))
    assert forms["L0"] == {"exclusive": 100}
    assert all(found == {"inclusive", "relative_days"} for found in l1_forms_by_scenario.values())
    assert len(l1_forms_by_scenario) == 10
    assert set(forms["L2"]) == {"relative_weeks", "business_days", "days_before_event", "moved_deadline"}
    assert min(forms["L2"].values()) >= 15
    assert {"earlier", "later"} <= directions


def test_business_day_deadlines_end_on_weekdays(derived):
    """The last acceptable day of a business-day deadline is itself a business day."""
    for case in derived:
        spec = case["metadata"]["request_facts"]["deadline"]
        if spec["form"] == "business_days":
            last_day = date.fromisoformat(case["expected_output"]["expected_request"]["latest_delivery_date"])
            assert (last_day - timedelta(days=1)).weekday() < 5


def test_trap_offers_supply_the_distractors(derived):
    """When an offer has another part or city, that value is the distractor."""
    for case in derived:
        facts = case["metadata"]["request_facts"]
        expected = case["expected_output"]["expected_request"]
        other_parts = {o["part_id"] for o in case["input"]["offers"]} - {expected["part_id"]}
        other_cities = {o["delivery_location"] for o in case["input"]["offers"]} - {expected["delivery_location"]}
        if facts["distractor_part"] and other_parts:
            assert facts["distractor_part"] in other_parts
        if facts["distractor_city"] and other_cities:
            assert facts["distractor_city"] in other_cities


def test_naive_regex_extractor_fails_beyond_l0(derived):
    """A regex baseline is exact on L0 but on at most 20% of L1 and of L2 records."""
    exact = Counter()
    for case in derived:
        if _naive_extract(case["input"]["request"]) == case["expected_output"]["expected_request"]:
            exact[case["metadata"]["level"]] += 1
    assert exact["L0"] == 100
    assert exact["L1"] <= NAIVE_CEILING * 100
    assert exact["L2"] <= NAIVE_CEILING * 100


def test_generation_is_reproducible_and_protects_sources(tmp_path):
    """Regeneration reproduces the stored bytes and never overwrites the source."""
    source_bytes = SOURCE.read_bytes()
    output = tmp_path / "v2.json"
    manifest = write_dataset(SOURCE, output, RULES)
    assert output.read_bytes() == TARGET.read_bytes()
    assert output.with_suffix(".manifest.json").read_bytes() == TARGET.with_suffix(".manifest.json").read_bytes()
    assert manifest["case_count"] == 300 and SOURCE.read_bytes() == source_bytes
    with pytest.raises(ValueError, match="must not overwrite"):
        write_dataset(SOURCE, SOURCE, RULES)


def test_extraction_prompt_documents_the_deadline_forms():
    """The agent prompt states the conversion rules the dataset relies on."""
    prompt = (ROOT / "demo02/prompts/extract_request.md").read_text()
    for phrase in ("no later than", "the day after D", "plus one more day", "PART-052", "part no. 52",
                   "weeks and N days", "business days are Monday to Friday", "before an event",
                   "moved K days earlier"):
        assert phrase in prompt
    assert "do not subtract a day" not in prompt
