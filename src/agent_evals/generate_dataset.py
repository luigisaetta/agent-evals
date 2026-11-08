"""
Author: L. Saetta
Date last modified: 2026-11-08
License: MIT
Description: Generate reproducible Express Order cases and provenance metadata.
"""

import argparse
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random

from agent_evals.selection import select_best_offer

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = (
    "all_eligible", "wrong_part_cheaper", "wrong_city_cheaper",
    "deadline_day_cheaper", "late_cheaper", "two_way_cost_tie",
    "three_way_cost_tie", "cost_before_speed", "one_cent_margin",
    "mixed_filters_single_eligible",
)
DATE_ORIGIN = date(2027, 1, 1)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def generate_cases(catalog_dir: Path, seed: int = 42) -> list[dict]:
    """Build 100 validated cases with balanced scenarios and winning positions.

    Args:
        catalog_dir: Directory containing the three reference catalogs.
        seed: Seed for catalog assignment, cost variation and offer ordering.

    Returns:
        Cases with separate inputs, reference outputs and metadata.

    Raises:
        ValueError: If catalog cardinality or generated winner is incorrect.
    """
    rng = random.Random(seed)
    catalogs = {
        name: json.loads((catalog_dir / f"{name}.json").read_text(), parse_float=Decimal)
        for name in ("parts", "suppliers", "locations")
    }
    parts, suppliers, locations = (catalogs[n] for n in ("parts", "suppliers", "locations"))
    for records, count in ((parts, 100), (suppliers, 50), (locations, 10)):
        if len(records) != count or len({r["id"] for r in records}) != count:
            raise ValueError(f"Expected {count} unique catalog records")
    rng.shuffle(parts)
    city_schedule = locations * 10
    rng.shuffle(city_schedule)
    supplier_schedule = suppliers * 12
    rng.shuffle(supplier_schedule)
    positions = [i % 6 for i in range(100)]
    rng.shuffle(positions)
    # Shuffle scenario assignment independently of requested parts and cities.
    schedule = [(scenario, repeat) for scenario in SCENARIOS for repeat in range(10)]
    rng.shuffle(schedule)
    cases = []
    for index, (scenario, repeat) in enumerate(schedule):
        case_id = f"EO-{index + 1:03d}"
        part, location = parts[index], city_schedule[index]
        deadline = DATE_ORIGIN + timedelta(days=rng.randint(14, 350))
        request = {
            "part_id": part["id"], "delivery_location": location["name"],
            "latest_delivery_date": deadline.isoformat(),
        }
        # Work in integer cents, with an illustrative express-delivery surcharge.
        base = int(Decimal(str(part["average_cost_eur"])) * 100)
        cost = base * rng.randint(90, 120) // 100 + rng.randint(1500, 4500)
        costs = [cost]
        for _ in range(5):
            costs.append(costs[-1] + rng.randint(100, 350))
        offsets = [-rng.randint(1, 8) for _ in range(6)]
        wrong_part = next(p["id"] for p in parts[index + 1:] + parts[:index]
                          if p["id"] != part["id"])
        wrong_city = rng.choice([p["name"] for p in locations if p["id"] != location["id"]])
        if scenario in {"wrong_part_cheaper", "wrong_city_cheaper", "deadline_day_cheaper", "late_cheaper"}:
            costs[1] = max(1, cost - rng.randint(100, 900))
        if scenario in {"two_way_cost_tie", "three_way_cost_tie"}:
            costs[1] = cost
            offsets[0], offsets[1] = -6, -3
            if scenario == "three_way_cost_tie":
                costs[2], offsets[2] = cost, -1
        if scenario == "cost_before_speed":
            offsets = [-1, -8, -7, -6, -5, -4]
        if scenario == "one_cent_margin":
            costs[1] = cost + 1
            offsets[0], offsets[1] = -1, -7
        if scenario == "mixed_filters_single_eligible":
            costs = [cost] + [max(1, cost - i * 100) for i in range(1, 6)]

        offers = []
        # Randomize neutral IDs independently of which candidate is the winner.
        id_numbers = rng.sample(range(1, 7), 6)
        for j in range(6):
            offers.append({
                "offer_id": f"{case_id}-OFF-{id_numbers[j]:02d}",
                "supplier_id": supplier_schedule[index * 6 + j]["id"],
                "part_id": part["id"], "delivery_location": location["name"],
                "delivery_date": (deadline + timedelta(days=offsets[j])).isoformat(),
                "total_cost_eur": costs[j] / 100,
            })
        if scenario == "all_eligible":
            offers[1]["supplier_id"] = offers[0]["supplier_id"]
        if scenario == "wrong_part_cheaper":
            offers[1]["part_id"] = wrong_part
        if scenario == "wrong_city_cheaper":
            offers[1]["delivery_location"] = wrong_city
        if scenario == "deadline_day_cheaper":
            offers[1]["delivery_date"] = deadline.isoformat()
        if scenario == "late_cheaper":
            offers[1]["delivery_date"] = (deadline + timedelta(days=rng.randint(1, 5))).isoformat()
        if scenario == "mixed_filters_single_eligible":
            offers[1]["part_id"] = wrong_part
            offers[2]["delivery_location"] = wrong_city
            offers[3]["delivery_date"] = deadline.isoformat()
            offers[4]["delivery_date"] = (deadline + timedelta(days=2)).isoformat()
            offers[5]["part_id"] = wrong_part
            offers[5]["delivery_location"] = wrong_city

        designed_winner = offers.pop(0)
        rng.shuffle(offers)
        offers.insert(positions[index], designed_winner)
        task_input = {"request": request, "offers": offers}
        reference = select_best_offer(task_input)
        if reference != designed_winner["offer_id"]:
            raise ValueError(f"Scenario construction failed for {case_id}")
        cases.append({
            "id": case_id, "input": task_input,
            "expected_output": {"expected_offer_id": reference},
            "metadata": {
                "scenario": scenario, "rules_version": "1.1", "dataset_version": "1.0",
                "seed": seed, "split": "development" if repeat < 2 else "evaluation",
            },
        })
    rng.shuffle(cases)
    return cases


def write_dataset(output: Path, catalog_dir: Path, rules_path: Path, seed: int = 42) -> dict:
    """Write the dataset and companion manifest and return the manifest.

    Args:
        output: Destination JSON file, replaced if it already exists.
        catalog_dir: Source catalog directory.
        rules_path: Source natural-language rules file.
        seed: Generation seed.

    Returns:
        Provenance hashes and coverage counts for the generated artifact.
    """
    cases = generate_cases(catalog_dir, seed)
    sources = {f"catalogs/{name}.json": _sha256(catalog_dir / f"{name}.json")
               for name in ("suppliers", "parts", "locations")}
    sources["rules/offer-selection.md"] = _sha256(rules_path)
    sources["code/generate_dataset.py"] = _sha256(Path(__file__))
    sources["code/selection.py"] = _sha256(Path(__file__).with_name("selection.py"))
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, cases)
    positions = Counter(str(next(i for i, o in enumerate(c["input"]["offers"], 1)
                                 if o["offer_id"] == c["expected_output"]["expected_offer_id"]))
                        for c in cases)
    manifest = {
        "dataset_version": "1.0", "rules_version": "1.1", "seed": seed,
        "date_origin": DATE_ORIGIN.isoformat(), "case_count": len(cases),
        "offers_per_case": 6, "dataset_sha256": _sha256(output),
        "source_sha256": sources,
        "scenario_counts": dict(sorted(Counter(c["metadata"]["scenario"] for c in cases).items())),
        "split_counts": dict(sorted(Counter(c["metadata"]["split"] for c in cases).items())),
        "winner_position_counts": dict(sorted(positions.items())),
    }
    _write_json(output.with_suffix(".manifest.json"), manifest)
    return manifest


def main() -> None:
    """Generate the dataset from command-line configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=ROOT / "data/datasets/express-order-v1.json")
    parser.add_argument("--catalog-dir", type=Path, default=ROOT / "data/catalogs")
    args = parser.parse_args()
    manifest = write_dataset(args.output, args.catalog_dir, ROOT / "rules/offer-selection.md", args.seed)
    print(f"Generated {manifest['case_count']} cases with 6 offers: {args.output}")


if __name__ == "__main__":
    main()
