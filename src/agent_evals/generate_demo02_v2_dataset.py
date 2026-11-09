"""
Author: L. Saetta
Date last modified: 2026-11-09
License: MIT
Description: Build the Demo02 v2 dataset with L0-L2 request-extraction difficulty levels.
"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import random

from agent_evals.dataset import file_hash, load_cases
from agent_evals.generate_demo02_dataset import DATE_STYLES, render_date, transform_cases
from agent_evals.tasks.offer_selection import TASK

ROOT = Path(__file__).resolve().parents[2]
LEVELS = ("L0", "L1", "L2")
DATASET_VERSION = "2.0"
DAY = timedelta(days=1)
INCLUSIVE_PHRASES = (
    "no later than {date}",
    "on or before {date}",
    "at the latest on {date}",
    "by the end of {date}",
)
L2_FORMS = ("relative_weeks", "business_days", "days_before_event", "moved_deadline")
PART_FORMS = ("canonical", "part_number", "p_n", "compact", "part_no")
L1_TEMPLATES = (
    "{other} has been discontinued. Please send your best offer for its replacement, "
    "{part}, delivered to our {city} plant {deadline}.",
    "We no longer use {other}. Our plant in {city} needs an offer for the replacement, "
    "{part}, delivered {deadline}.",
    "Instead of {other}, which is no longer available, please quote {part} for our plant "
    "in {city}, delivered {deadline}.",
    "Replacing the discontinued {other}: we need the best offer for {part} at our {city} "
    "plant, delivered {deadline}.",
)
L2_INTROS = (
    "I am writing from our procurement office in {other_city} on behalf of our plant in {city}.",
    "Our {other_city} plant is closed for maintenance, so this order is for our plant in {city}.",
)


def render_part(part_id: str, form: str) -> str:
    """Write a canonical part identifier in one of the supported surface forms.

    Args:
        part_id: Canonical identifier such as PART-052.
        form: One of PART_FORMS.

    Returns:
        Text naming the part, for example "part number 052".

    Raises:
        ValueError: If the identifier or form is not supported.
    """
    prefix, digits = part_id.split("-")
    if prefix != "PART" or len(digits) != 3 or not digits.isdigit():
        raise ValueError("Part identifiers must have the form PART-NNN")
    forms = {
        "canonical": f"part {part_id}",
        "part_number": f"part number {digits}",
        "p_n": f"P/N PART {digits}",
        "compact": f"part PART{digits}",
        "part_no": f"part no. {int(digits)}",
    }
    if form not in forms:
        raise ValueError("Unknown part form")
    return forms[form]


def business_day_anchor(last_day: date, count: int) -> date:
    """Find the anchor whose count-th following business day is last_day.

    Business days are Monday to Friday, without holidays; counting starts the
    day after the anchor.

    Args:
        last_day: Last acceptable delivery day; must be a weekday.
        count: Positive number of business days.

    Returns:
        The day before the first counted business day.

    Raises:
        ValueError: If last_day falls on a weekend or count is not positive.
    """
    if last_day.weekday() >= 5 or count <= 0:
        raise ValueError("Business-day deadlines need a weekday and a positive count")
    day, counted = last_day, 0
    while True:
        if day.weekday() < 5:
            counted += 1
            if counted == count:
                return day - DAY
        day -= DAY


def _pick_distractor(values: list[str], trap_values: list[str], exclude: str,
                     rng: random.Random) -> str:
    """Prefer a trap offer's value; otherwise choose another catalog value."""
    traps = sorted({value for value in trap_values if value != exclude})
    if traps:
        return traps[0]
    return rng.choice([value for value in values if value != exclude])


def _date_text(value: date, rng: random.Random) -> str:
    """Render a date in a randomly selected unambiguous English style."""
    return render_date(value.isoformat(), rng.choice(DATE_STYLES))


def _build_l1(request: dict, offers: list[dict], catalogs: dict, index: int,
              rng: random.Random) -> tuple[str, dict]:
    """Compose an L1 request with an inclusive or relative-days deadline.

    Even positions within a scenario use a relative-days deadline; odd positions
    use an inclusive one. The part is non-canonical and a discontinued part comes first.
    """
    deadline = date.fromisoformat(request["latest_delivery_date"])
    last_day = deadline - DAY
    if index % 2 == 0:
        days = rng.randint(10, 40)
        anchor = last_day - timedelta(days=days)
        deadline_text = f"no later than {days} calendar days after {_date_text(anchor, rng)}"
        spec = {"form": "relative_days", "anchor": anchor.isoformat(), "days": days}
        key_dates = [anchor.isoformat()]
    else:
        deadline_text = rng.choice(INCLUSIVE_PHRASES).format(date=_date_text(last_day, rng))
        spec = {"form": "inclusive", "stated": last_day.isoformat()}
        key_dates = [last_day.isoformat()]
    other_part = _pick_distractor(catalogs["parts"], [o["part_id"] for o in offers],
                                  request["part_id"], rng)
    part_form = rng.choice(PART_FORMS[1:])
    text = rng.choice(L1_TEMPLATES).format(
        other=other_part, part=render_part(request["part_id"], part_form),
        city=request["delivery_location"], deadline=deadline_text,
    )
    facts = {"deadline": spec, "key_dates": key_dates, "other_dates": [],
             "part_form": part_form, "distractor_part": other_part, "distractor_city": None}
    return text, facts


def _l2_deadline(deadline: date, form: str, index: int,
                 rng: random.Random) -> tuple[str, dict, date | None]:
    """Build the L2 deadline sentence for one arithmetic form.

    Args:
        deadline: Exclusive deadline that the sentence must imply.
        form: One of L2_FORMS.
        index: Position of the case within its scenario, for direction alternation.
        rng: Seeded generator.

    Returns:
        Sentence, deadline specification, and the email date when the form
        refers to it (otherwise None, and the caller picks a distractor email date).
    """
    last_day = deadline - DAY
    if form == "relative_weeks":
        weeks, days = rng.randint(2, 5), rng.randint(1, 6)
        anchor = last_day - timedelta(days=7 * weeks + days)
        sentence = (f"The delivery must arrive no later than {weeks} weeks and {days} days "
                    f"after the date of this request ({_date_text(anchor, rng)}).")
        return sentence, {"form": form, "anchor": anchor.isoformat(), "weeks": weeks,
                          "days": days}, anchor
    if form == "business_days":
        count = rng.randint(8, 25)
        anchor = business_day_anchor(last_day, count)
        sentence = (f"The delivery must arrive no later than {count} business days after the "
                    f"date of this request ({_date_text(anchor, rng)}); business days are "
                    "Monday to Friday.")
        return sentence, {"form": form, "anchor": anchor.isoformat(), "business_days": count}, anchor
    if form == "days_before_event":
        days = rng.randint(2, 10)
        event = last_day + timedelta(days=days)
        sentence = (f"Our production line restarts on {_date_text(event, rng)}, and the delivery "
                    f"must arrive no later than {days} calendar days before that date.")
        return sentence, {"form": form, "event": event.isoformat(), "days": days}, None
    if form == "moved_deadline":
        shift = rng.randint(2, 9)
        direction = "earlier" if (index // 4) % 2 == 0 else "later"
        original = deadline + timedelta(days=shift if direction == "earlier" else -shift)
        sentence = (f"The original deadline was strictly before {_date_text(original, rng)}, but it "
                    f"has been moved {shift} days {direction}; the delivery must arrive before "
                    "the new deadline.")
        return sentence, {"form": form, "original": original.isoformat(), "shift_days": shift,
                          "direction": direction}, None
    raise ValueError("Unknown L2 deadline form")


def _build_l2(request: dict, offers: list[dict], catalogs: dict, index: int,
              rng: random.Random) -> tuple[str, dict]:
    """Compose an L2 email whose deadline always requires date arithmetic.

    Forms rotate with the case's position within its scenario. The business-day
    form is skipped when the last acceptable day falls on a weekend.
    """
    deadline = date.fromisoformat(request["latest_delivery_date"])
    form = L2_FORMS[index % len(L2_FORMS)]
    if form == "business_days" and (deadline - DAY).weekday() >= 5:
        form = L2_FORMS[(index + 1) % len(L2_FORMS)]
    sentence, spec, anchor = _l2_deadline(deadline, form, index, rng)
    email_date = anchor or deadline - timedelta(days=rng.randint(14, 45))
    last_delivery = email_date - timedelta(days=rng.randint(20, 90))
    other_city = _pick_distractor(catalogs["cities"], [o["delivery_location"] for o in offers],
                                  request["delivery_location"], rng)
    part_form = rng.choice(PART_FORMS)
    part_text = render_part(request["part_id"], part_form)
    other_part = None
    if (index // 2) % 2 == 0:
        other_part = _pick_distractor(catalogs["parts"], [o["part_id"] for o in offers],
                                      request["part_id"], rng)
        part_sentence = f"{other_part} has been discontinued, so we need its replacement, {part_text}."
    else:
        part_sentence = f"We need {part_text}."
    body = [
        part_sentence,
        sentence,
        f"For reference, our last delivery of this part arrived on {_date_text(last_delivery, rng)}.",
    ]
    rng.shuffle(body)
    intro = rng.choice(L2_INTROS).format(other_city=other_city, city=request["delivery_location"])
    text = "\n".join([
        f"Date: {_date_text(email_date, rng)}",
        "Subject: Urgent quotation request",
        "",
        "Hello,",
        "",
        " ".join([intro, *body]),
        "Please send us your best offer.",
        "",
        "Best regards,",
        "Procurement team",
    ])
    key_dates = [spec[key] for key in ("anchor", "event", "original") if key in spec]
    other_dates = [last_delivery.isoformat()]
    if anchor is None:
        other_dates.insert(0, email_date.isoformat())
    facts = {"deadline": spec, "key_dates": key_dates, "other_dates": other_dates,
             "part_form": part_form, "distractor_part": other_part, "distractor_city": other_city}
    return text, facts


def build_cases(source_cases: list[dict], catalogs: dict, seed: int = 42) -> list[dict]:
    """Derive L0, L1 and L2 records for every source case without changing offers or labels.

    Args:
        source_cases: Structured cases already validated against their manifest.
        catalogs: Lists of catalog part identifiers ("parts") and city names ("cities").
        seed: Seed controlling wording, date styles and distractor choices.

    Returns:
        Three records per source case, in source order and level order.
    """
    rng = random.Random(seed)
    l0_cases = transform_cases(source_cases, seed)
    scenario_positions = Counter()
    derived = []
    for source, l0 in zip(source_cases, l0_cases):
        request, offers = source["input"]["request"], source["input"]["offers"]
        index = scenario_positions[source["metadata"]["scenario"]]
        scenario_positions[source["metadata"]["scenario"]] += 1
        stated = request["latest_delivery_date"]
        l0_facts = {"deadline": {"form": "exclusive", "stated": stated}, "key_dates": [stated],
                    "other_dates": [], "part_form": "canonical", "distractor_part": None,
                    "distractor_city": None}
        texts = {
            "L0": (l0["input"]["request"], l0_facts),
            "L1": _build_l1(request, offers, catalogs, index, rng),
            "L2": _build_l2(request, offers, catalogs, index, rng),
        }
        for level in LEVELS:
            text, facts = texts[level]
            record = deepcopy(source)
            record["id"] = f"{source['id']}-{level}"
            record["input"]["request"] = text
            record["expected_output"] = {
                "expected_offer_id": source["expected_output"]["expected_offer_id"],
                "expected_request": deepcopy(request),
            }
            record["metadata"].update({
                "demo": "demo02", "dataset_version": DATASET_VERSION,
                "source_dataset_version": source["metadata"]["dataset_version"],
                "input_format": "natural_language_request_structured_offers",
                "source_case_id": source["id"], "level": level, "generation_seed": seed,
                "request_facts": facts,
            })
            derived.append(record)
    return derived


def load_catalogs(root: Path = ROOT) -> dict:
    """Read the part identifiers and plant city names used for distractors.

    Args:
        root: Repository root containing data/catalogs.

    Returns:
        Dictionary with sorted "parts" identifiers and "cities" names.
    """
    parts = json.loads((root / "data/catalogs/parts.json").read_text())
    locations = json.loads((root / "data/catalogs/locations.json").read_text())
    return {"parts": sorted(p["id"] for p in parts), "cities": sorted(l["name"] for l in locations)}


def write_dataset(source: Path, output: Path, rules: Path, seed: int = 42) -> dict:
    """Write the Demo02 v2 dataset and its provenance manifest.

    Args:
        source: Original structured dataset with a companion manifest.
        output: Separate destination file; an existing copy is replaced.
        rules: Unchanged business rules used by the source dataset.
        seed: Seed for wording and distractor choices.

    Returns:
        Manifest containing hashes, counts and source lineage.

    Raises:
        ValueError: If source validation fails or output would overwrite a source.
    """
    source_manifest = source.with_suffix(".manifest.json")
    output_manifest = output.with_suffix(".manifest.json")
    protected = {path.resolve() for path in (source, source_manifest, rules)}
    if output.resolve() in protected or output_manifest.resolve() in protected:
        raise ValueError("Demo02 v2 output must not overwrite source artifacts")
    original = load_cases(source, rules, "all", None, TASK)
    cases = build_cases(original, load_catalogs(), seed)
    versions = json.loads(source_manifest.read_text())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")

    def count(key) -> dict:
        return dict(sorted(Counter(key(c) for c in cases).items()))

    def level_and(field):
        return lambda c: f"{c['metadata']['level']}:{field(c['metadata']['request_facts'])}"

    code = Path(__file__).parent
    manifest = {
        "dataset_name": "demo02-express-order-v2", "dataset_version": DATASET_VERSION,
        "rules_version": versions["rules_version"],
        "input_format": "natural_language_request_structured_offers",
        "generation_seed": seed, "case_count": len(cases), "source_case_count": len(original),
        "offers_per_case": 6, "dataset_sha256": file_hash(output),
        "source_sha256": {
            f"datasets/{source.name}": file_hash(source),
            f"datasets/{source_manifest.name}": file_hash(source_manifest),
            TASK.rules_manifest_key: file_hash(rules),
            "catalogs/parts.json": file_hash(ROOT / "data/catalogs/parts.json"),
            "catalogs/locations.json": file_hash(ROOT / "data/catalogs/locations.json"),
            "code/generate_demo02_dataset.py": file_hash(code / "generate_demo02_dataset.py"),
            "code/generate_demo02_v2_dataset.py": file_hash(Path(__file__)),
        },
        "level_counts": count(lambda c: c["metadata"]["level"]),
        "split_counts": count(lambda c: c["metadata"]["split"]),
        "scenario_counts": count(lambda c: c["metadata"]["scenario"]),
        "deadline_form_counts": count(level_and(lambda f: f["deadline"]["form"])),
        "part_form_counts": count(level_and(lambda f: f["part_form"])),
    }
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    """Generate the Demo02 v2 dataset from CLI paths and seed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/datasets/express-order-v1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/datasets/demo02-express-order-v2.json")
    parser.add_argument("--rules", type=Path, default=ROOT / "rules/offer-selection.md")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = write_dataset(args.source, args.output, args.rules, args.seed)
    print(f"Created {manifest['case_count']} Demo02 v2 records "
          f"({manifest['source_case_count']} source cases x {len(LEVELS)} levels): {args.output}")


if __name__ == "__main__":
    main()
