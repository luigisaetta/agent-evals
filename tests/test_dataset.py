"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Check synthetic scenario semantics, coverage and reproducibility.
"""

from collections import Counter
from datetime import date
from decimal import Decimal
import hashlib
import json

from agent_evals.generate_dataset import ROOT, SCENARIOS, generate_cases, write_dataset
from agent_evals.selection import select_best_offer

CATALOG_DIR = ROOT / "data/catalogs"


def _check_cases(cases):
    assert len(cases) == len({c["id"] for c in cases}) == 100
    catalogs = {name: json.loads((CATALOG_DIR / f"{name}.json").read_text())
                for name in ("parts", "suppliers", "locations")}
    part_ids = {p["id"] for p in catalogs["parts"]}
    supplier_ids = {p["id"] for p in catalogs["suppliers"]}
    cities = {p["name"] for p in catalogs["locations"]}
    assert {c["input"]["request"]["part_id"] for c in cases} == part_ids
    assert {o["supplier_id"] for c in cases for o in c["input"]["offers"]} == supplier_ids
    assert set(Counter(c["input"]["request"]["delivery_location"] for c in cases).values()) == {10}
    assert Counter(c["metadata"]["scenario"] for c in cases) == {s: 10 for s in SCENARIOS}
    assert Counter(c["metadata"]["split"] for c in cases) == {"development": 20, "evaluation": 80}
    positions = Counter()
    for case in cases:
        task = case["input"]
        assert set(task) == {"request", "offers"}
        offers, request = task["offers"], task["request"]
        assert len(offers) == len({o["offer_id"] for o in offers}) == 6
        for offer in offers:
            assert offer["part_id"] in part_ids
            assert offer["supplier_id"] in supplier_ids
            assert offer["delivery_location"] in cities
        # Independent exhaustive dominance check, without calling oracle helpers.
        eligible = [o for o in offers if o["part_id"] == request["part_id"]
                    and o["delivery_location"] == request["delivery_location"]
                    and date.fromisoformat(o["delivery_date"]) < date.fromisoformat(request["latest_delivery_date"])]
        ranks = {o["offer_id"]: (Decimal(str(o["total_cost_eur"])), date.fromisoformat(o["delivery_date"]))
                 for o in eligible}
        winners = [key for key, rank in ranks.items() if all(rank <= other for other in ranks.values())]
        assert winners == [case["expected_output"]["expected_offer_id"]]
        assert select_best_offer(task) == winners[0]
        winner = next(o for o in offers if o["offer_id"] == winners[0])
        positions[offers.index(winner)] += 1
        scenario = case["metadata"]["scenario"]
        assert sum(c["metadata"]["scenario"] == scenario and c["metadata"]["split"] == "development"
                   for c in cases) == 2
        cheaper = [o for o in offers if o["total_cost_eur"] < winner["total_cost_eur"]]
        if scenario == "all_eligible":
            assert len(eligible) == 6 and len({o["total_cost_eur"] for o in eligible}) == 6
            assert len({o["supplier_id"] for o in offers}) < 6
        elif scenario in {"wrong_part_cheaper", "wrong_city_cheaper", "deadline_day_cheaper", "late_cheaper"}:
            assert len(eligible) == 5 and len(cheaper) == 1
            bad = cheaper[0]
            if scenario == "wrong_part_cheaper":
                assert bad["part_id"] != request["part_id"]
            elif scenario == "wrong_city_cheaper":
                assert bad["delivery_location"] != request["delivery_location"]
            elif scenario == "deadline_day_cheaper":
                assert bad["delivery_date"] == request["latest_delivery_date"]
            else:
                assert bad["delivery_date"] > request["latest_delivery_date"]
        elif scenario in {"two_way_cost_tie", "three_way_cost_tie"}:
            ties = [o for o in eligible if o["total_cost_eur"] == winner["total_cost_eur"]]
            assert len(ties) == (2 if scenario == "two_way_cost_tie" else 3)
            assert winner["delivery_date"] == min(o["delivery_date"] for o in ties)
        elif scenario in {"cost_before_speed", "one_cent_margin"}:
            assert len(eligible) == 6
            if scenario == "cost_before_speed":
                assert all(o["delivery_date"] < winner["delivery_date"] for o in offers if o != winner)
            if scenario == "one_cent_margin":
                prices = sorted(Decimal(str(o["total_cost_eur"])) for o in eligible)
                assert prices[1] - prices[0] == Decimal("0.01")
        else:
            assert len(eligible) == 1 and len(cheaper) == 5
    assert set(positions) == set(range(6)) and set(positions.values()) <= {16, 17}


def test_generated_and_stored_cases():
    """Verify reference labels and scenario coverage on generated and stored data."""
    cases = generate_cases(CATALOG_DIR)
    _check_cases(cases)
    stored = json.loads((ROOT / "data/datasets/express-order-v1.json").read_text())
    assert stored == cases


def test_reproducible_artifacts_and_seed_variation(tmp_path):
    """Regeneration preserves bytes and hashes; another seed changes the cases."""
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    rules = ROOT / "rules/offer-selection.md"
    manifest = write_dataset(first, CATALOG_DIR, rules)
    assert write_dataset(second, CATALOG_DIR, rules) == manifest
    assert first.read_bytes() == second.read_bytes()
    assert first.with_suffix(".manifest.json").read_bytes() == second.with_suffix(".manifest.json").read_bytes()
    assert manifest["dataset_sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()
    assert json.loads((ROOT / "data/datasets/express-order-v1.manifest.json").read_text()) == manifest
    alternate = generate_cases(CATALOG_DIR, seed=43)
    assert alternate != json.loads(first.read_text())
    _check_cases(alternate)
