"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Verbalize only Express Order requests while preserving structured offers.
"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import random

from agent_evals.dataset import file_hash, load_cases
from agent_evals.tasks.offer_selection import TASK

ROOT = Path(__file__).resolve().parents[2]
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
DATE_STYLES = ("iso", "day_month_year", "month_day_year")
REQUEST_TEMPLATES = (
    "We need the best offer for delivery of part {part} to our plant in {city} strictly before {deadline}.",
    "Our plant in {city} needs an offer for part {part}, with delivery earlier than {deadline}.",
    "Please find the best quotation for delivering part {part} to the plant in {city} before {deadline}; that date is not included.",
    "We are looking for an offer to deliver part {part} to our {city} plant strictly before {deadline}.",
    "We require the best offer for part {part} to be delivered to the plant in {city} earlier than {deadline}.",
    "Please provide a quotation for delivery of part {part} to our plant in {city} before {deadline}; delivery on that date is not acceptable.",
    "For an Express Order, we need an offer for delivery of part {part} to our plant in {city}, with an exclusive deadline of {deadline}.",
    "Could you identify the best quote for supplying part {part} to the plant in {city} strictly earlier than {deadline}?",
    "For our plant in {city}, we need the best offer for delivery of part {part} before {deadline}, excluding the deadline itself.",
    "We would like an offer for shipping part {part} to our {city} plant so that it arrives strictly before {deadline}.",
)


def render_date(iso_date: str, style: str) -> str:
    """Express a date unambiguously using locale-independent English month names.

    Args:
        iso_date: Source date in YYYY-MM-DD format.
        style: One of the supported date-style names.

    Returns:
        A calendar date representing exactly the source day.

    Raises:
        ValueError: If the date or style is invalid.
    """
    value = date.fromisoformat(iso_date)
    if style == "iso":
        return iso_date
    if style == "day_month_year":
        return f"{value.day} {MONTHS[value.month - 1]} {value.year}"
    if style == "month_day_year":
        return f"{MONTHS[value.month - 1]} {value.day}, {value.year}"
    raise ValueError("Unknown English date style")


def transform_cases(source_cases: list[dict], seed: int = 42) -> list[dict]:
    """Verbalize requests while preserving offers, order and reference outputs.

    Args:
        source_cases: Structured cases already validated against their manifest.
        seed: Seed controlling template and date-style assignment.

    Returns:
        Case records with an English input.request and unchanged input.offers.
    """
    rng = random.Random(seed)
    request_styles = [i % len(REQUEST_TEMPLATES) for i in range(len(source_cases))]
    rng.shuffle(request_styles)
    transformed = []
    for source, request_style in zip(source_cases, request_styles):
        task_input = source["input"]
        request = task_input["request"]
        date_style = rng.choice(DATE_STYLES)
        request_text = REQUEST_TEMPLATES[request_style].format(
            part=request["part_id"], city=request["delivery_location"],
            deadline=render_date(request["latest_delivery_date"], date_style),
        )
        result = deepcopy(source)
        result["input"]["request"] = request_text
        result["metadata"].update({
            "demo": "demo02", "input_format": "natural_language_request_structured_offers",
            "source_case_id": source["id"], "transformation_seed": seed,
            "request_template": f"request-{request_style + 1:02d}",
            "request_date_style": date_style,
        })
        transformed.append(result)
    return transformed


def write_dataset(source: Path, output: Path, rules: Path, seed: int = 42) -> dict:
    """Write the demo02 dataset and a companion provenance manifest.

    Args:
        source: Original structured dataset, with a companion manifest.
        output: Separate destination file; an existing review copy is replaced.
        rules: Unchanged business rules used by the source dataset.
        seed: Seed for repeatable language variation.

    Returns:
        Manifest containing hashes, counts and source lineage.

    Raises:
        ValueError: If source validation fails or output would overwrite a source.
    """
    source_manifest = source.with_suffix(".manifest.json")
    output_manifest = output.with_suffix(".manifest.json")
    protected = {path.resolve() for path in (source, source_manifest, rules)}
    if output.resolve() in protected or output_manifest.resolve() in protected:
        raise ValueError("Demo02 output must not overwrite source artifacts")
    original = load_cases(source, rules, "all", None, TASK)
    cases = transform_cases(original, seed)
    versions = json.loads(source_manifest.read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    manifest = {
        "dataset_name": "demo02-express-order-v1", "dataset_version": "1.0",
        "rules_version": versions["rules_version"], "input_format": "natural_language_request_structured_offers",
        "transformation_seed": seed, "case_count": len(cases), "offers_per_case": 6,
        "dataset_sha256": file_hash(output),
        "source_sha256": {
            f"datasets/{source.name}": file_hash(source),
            f"datasets/{source_manifest.name}": file_hash(source_manifest),
            TASK.rules_manifest_key: file_hash(rules),
            "code/generate_demo02_dataset.py": file_hash(Path(__file__)),
        },
        "scenario_counts": dict(sorted(Counter(c["metadata"]["scenario"] for c in cases).items())),
        "split_counts": dict(sorted(Counter(c["metadata"]["split"] for c in cases).items())),
        "request_template_counts": dict(sorted(Counter(c["metadata"]["request_template"] for c in cases).items())),
        "request_date_style_counts": dict(sorted(Counter(c["metadata"]["request_date_style"] for c in cases).items())),
    }
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    """Generate the natural-language-request dataset from CLI paths and seed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/datasets/express-order-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/datasets/demo02-express-order-v1.json")
    parser.add_argument("--rules", type=Path, default=ROOT / "rules/offer-selection.md")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = write_dataset(args.source, args.output, args.rules, args.seed)
    print(f"Created {manifest['case_count']} cases with natural-language requests and structured offers: {args.output}")


if __name__ == "__main__":
    main()
