# Demo02 v2: request extraction with graded difficulty

## Problem

In `demo02-express-order-v1.json`, three regular expressions (a `PART-NNN` match, a city-name match, and three date formats) recover every request exactly. The extraction step therefore cannot distinguish one model from another. Version 2 makes the request text require interpretation while keeping every case's underlying business facts, offers, and expected answer unchanged.

## Scope

* Add `src/agent_evals/generate_demo02_v2_dataset.py`, `data/datasets/demo02-express-order-v2.json`, and its manifest.
* Derive three paired variants of each of the 100 source cases: levels `L0`, `L1`, and `L2` (300 records).
* Update the Demo02 extraction prompt so that it returns the exclusive deadline for every supported phrasing, and normalizes part identifiers.
* Keep `demo02-express-order-v1.json`, its generator, and the structured source dataset unchanged.

## Non-goals

* No catalog lookups: parts remain identified by number and plants by English city name.
* No unanswerable or ambiguous requests; every request has exactly one correct extraction.
* No model calls, Langfuse uploads, or evaluation runner adapter in this change.

## Invariants

* `input` contains `request` (an English string) and `offers` (the unchanged six source offers, in the same order).
* `expected_output.expected_offer_id` is unchanged. `expected_output.expected_request` adds the source structured request, so the extraction step can be scored separately.
* Record IDs are `<source id>-L0|L1|L2`. Source scenario, split, and rules version are preserved. `metadata.dataset_version` is `2.0`, matching the manifest, and `metadata.source_dataset_version` records the source version; `metadata.source_case_id`, `metadata.level`, and `metadata.request_facts` are added.
* Text is composed deterministically from fixed fragments with seed 42. No language model generates text, so the reference is correct by construction.

## Phrasing semantics

The rules keep an exclusive deadline `D` (`latest_delivery_date`). Every phrase has exactly one interpretation:

| Form | Example wording | Stated date | Exclusive deadline |
| --- | --- | --- | --- |
| `exclusive` | "strictly before", "earlier than", "before …; that date is not included" | `D` | `D` |
| `inclusive` | "no later than", "on or before", "at the latest on", "by the end of" | `D - 1 day` | stated date `+ 1 day` |
| `relative_days` | "no later than N calendar days after A" | anchor `A` | `A + N + 1 day` |
| `relative_weeks` | "no later than W weeks and N days after the date of this request (A)" | anchor `A` | `A + 7W + N + 1 day` |
| `business_days` | "no later than N business days after the date of this request (A)" | anchor `A` | the Nth business day after `A`, `+ 1 day` |
| `days_before_event` | "our production line restarts on E … no later than N calendar days before that date" | event `E` | `E - N + 1 day` |
| `moved_deadline` | "the original deadline was strictly before X, but it has been moved K days earlier/later" | original `X` | `X - K` or `X + K` |

Business days are Monday to Friday, without public holidays; counting starts the day after `A`. The business-day form is used only when `D - 1` is a weekday, so that the last acceptable day is itself a business day.

Part numbers appear as `PART-052`, `part number 052`, `P/N PART 052`, `PART052`, or `part no. 52`; the extraction normalizes them to `PART-NNN` with three digits.

Distractors are facts that must not be extracted. They are clearly marked as not being the request:

* A discontinued or previously ordered part being replaced ("PART-031 has been discontinued; please quote its replacement …").
* A city that is not the destination (the sender's office, or a plant that is closed).
* Dates that are not the deadline (the request date in an email header, the last delivery of the part).

Whenever an offer carries a different part or city (for example in `wrong_part_cheaper`, `wrong_city_cheaper`, and `mixed_filters_single_eligible`), the distractor uses that trap value, so an extraction error leads to the trap offer. Otherwise the distractor is another catalog part or city.

## Levels

| Level | Form | Deadline | Part | Distractors |
| --- | --- | --- | --- | --- |
| `L0` | One sentence, identical to v1 | `exclusive` | Canonical | None |
| `L1` | One or two sentences | Alternating `inclusive` and `relative_days` within each scenario | Non-canonical form | Discontinued part placed before the requested part |
| `L2` | Short email with subject, greeting, and signature | Rotating `relative_weeks`, `business_days`, `days_before_event`, `moved_deadline` within each scenario | Any form | Distractor city, the email date (unless it is the anchor), a last-delivery date, and an alternating distractor part |

Every L2 deadline requires date arithmetic. About half the cases belong to scenarios where a one-day extraction error changes the selected offer (see the sensitivity note in `docs/demo02-dataset.md`), so arithmetic errors also affect final correctness.

### Revision history

Version 2.0 was first generated with L1 always `inclusive` and L2 alternating `relative`, `inclusive`, and `exclusive`. On 2026-11-09, `openai.gpt-oss-20b` extracted 237 of 240 evaluation records exactly (all errors were one-day errors on relative L2 deadlines) and selected every reachable offer correctly, so the levels were saturated. The dataset was then revised in place, keeping version 2.0 at the user's request: the earlier `relative` form moved to L1, and L2 received the four arithmetic forms above. The earlier dataset, manifest, generator, and prompt are kept with that run's local results (`data/runs/20261109T090159Z-7c76b9d6/dataset-snapshot/`, git-ignored); its dataset SHA-256 is `fd19a0bc070341e4e0dbdd12e69ed0231065db65b071c4e93c6fbbed2c4022ad`.

## Acceptance criteria

1. There are 300 records, three per source case; offers and `expected_offer_id` equal the source, and splits are 60 development and 240 evaluation records.
2. `expected_request` equals the source request, and the deterministic selector applied to it returns `expected_offer_id`.
3. A test recomputes the exclusive deadline from `request_facts` without using generator code, and checks that the stated dates, part digits, and city names appear in the text.
4. L1 uses `inclusive` and `relative_days` in every scenario; every L2 record uses one of the four arithmetic forms, each form appears at least 15 times, and `moved_deadline` appears in both directions.
5. A naive regex extractor (first `PART-NNN`, first catalog city, first date taken as the deadline) is exact on all L0 records and on at most 20% of L1 and of L2 records.
6. Requests contain no offer IDs, supplier IDs, prices, or expected-answer fields.
7. Generation is byte-for-byte reproducible and refuses to overwrite source artifacts.
8. The extraction prompt documents every deadline form and part normalization; existing tests continue to pass.

## Verification

Offline `pytest` only. Measuring the effect on real models (extraction accuracy per level) is a separate, explicitly run experiment.

## Verification results (2026-11-09, offline)

* `pytest -q`: 106 tests pass in the `agent-evals` environment, including `tests/test_demo02_v2_dataset.py`.
* After the in-place revision: the naive regex extractor is exact on 100/100 L0, 0/100 L1, and 0/100 L2 records. A one-day deadline error changes the selected offer in 43/100 L1 and 43/100 L2 records. L2 deadline forms: 30 `relative_weeks`, 25 `business_days`, 25 `days_before_event`, 20 `moved_deadline`.
* Black and Pylint are not installed in the `agent-evals` environment and were not run.
* The Demo02 evaluation adapter accepts both reference shapes and uses this dataset by default; an offline `--dry-run --split all` validates 300 records (see `demo02/evaluation-spec.md`).
* A first generation stored the source `dataset_version` (`1.0`) in each record while the manifest declared `2.0`, which the shared loader rejects. Records now carry `dataset_version: 2.0` and `source_dataset_version: 1.0`, and a test runs the shared loader.
* Not yet verified: live extraction accuracy per level.

## Live results (2026-11-09)

Full held-out runs (240 evaluation records, dataset SHA-256 prefix `33dcebb1b1c8`, 2,048 output tokens), counted from each run's local `results.jsonl`. An extraction error is an extraction different from `expected_request`, including invalid output; a hidden error is an extraction error with a correct final answer.

| Model | Run ID | Correct | Incorrect | Invalid output | Extraction errors (L0/L1/L2) | Hidden |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| `openai.gpt-oss-20b` | `20261109T094835Z-7af10c48` | 232 | 5 | 3 | 0/1/8 | 3 |
| `openai.gpt-oss-20b` | `20261109T111025Z-0c82644a` | 233 | 5 | 2 | 0/1/10 | 5 |
| `openai.gpt-oss-120b` | `20261109T101911Z-5ce9b1ce` | 240 | 0 | 0 | 0/0/2 | 2 |
| `openai.gpt-6.1-terra` | `20261109T121943Z-d0757262` | 239 | 0 | 1 | 0/1/0 | 0 |

* Four `gpt-oss-20b` invalid outputs were business-day extractions truncated at the token limit (`incomplete`); one (`EO-091-L2`, moved deadline) returned a null deadline.
* `EO-081-L1` and `EO-081-L2` (first 20b run) and `EO-081-L2` (second) are selection errors on a correct extraction.
* The `gpt-6.1-terra` failure (`EO-061-L1`) computed the right date but wrote `2027-2027-11-25`.
* The two 20b runs use identical inputs and settings; their failing cases partly differ.
* Langfuse publication was `submitted_unverified`; remote scores were not checked through the read API.
