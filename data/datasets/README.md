# Express Order synthetic dataset

## Dataset variants

The original `express-order-v1.json` uses structured request/offer inputs. [demo02-express-order-v1.json](https://github.com/luigisaetta/agent-evals/blob/main/data/datasets/demo02-express-order-v1.json) replaces only `input.request` with varied English delivery-request text, while `input.offers` remains the exact same six structured JSON offers and reference answers stay unchanged. See the [Demo02 data guide](https://github.com/luigisaetta/agent-evals/blob/main/docs/demo02-dataset.md) for provenance and the [Demo02 LangGraph agent](https://github.com/luigisaetta/agent-evals/blob/main/demo02/README.md) for single-case execution and full-dataset evaluation with Langfuse publication.

[demo02-express-order-v2.json](demo02-express-order-v2.json) derives three paired records (L0, L1, L2) from each source case, so that request extraction requires interpretation: inclusive and relative deadlines, non-canonical part numbers, and distractor parts, cities and dates. Offers and `expected_offer_id` are unchanged, and `expected_output.expected_request` adds the reference extraction. See the [Demo02 data guide](https://github.com/luigisaetta/agent-evals/blob/main/docs/demo02-dataset.md#version-2-graded-extraction-difficulty).

## Original structured dataset

[express-order-v1.json](express-order-v1.json) contains 100 cases, each with six offers and one unique expected winner under rules version 1.1. [The manifest](express-order-v1.manifest.json) records provenance hashes and coverage counts.

All data is synthetic and generated from the reference catalogs, using seed 42 and fixed date origin 2027-01-01. Each of the 100 parts is requested once, each of the 10 plant cities is requested ten times, and all 50 suppliers appear. Some cases include multiple offers from the same supplier. Costs are illustrative total offer amounts in euros, not market quotations.

## Scenario distribution

| Scenario | Cases |
| --- | ---: |
| All eligible, distinct costs | 10 |
| Cheaper offer for the wrong part | 10 |
| Cheaper offer for the wrong city | 10 |
| Cheaper offer delivering on the excluded deadline | 10 |
| Cheaper offer delivering after the deadline | 10 |
| Two-way lowest-cost tie, earliest delivery wins | 10 |
| Three-way lowest-cost tie, earliest delivery wins | 10 |
| Lower cost wins over faster delivery | 10 |
| One-cent difference decides the winner | 10 |
| Mixed eligibility failures leave one valid offer | 10 |

Case and offer ordering are shuffled. The winner occupies each of the six offer positions 16 or 17 times. IDs are neutral and do not encode the winner.

## Case format and evaluation use

Each record contains:

* `id`: stable case identifier for this dataset version and seed.
* `input`: `request` and `offers`; only this object and the rules go to the model.
* `expected_output.expected_offer_id`: reference answer computed by the deterministic oracle, kept outside the model input.
* `metadata`: scenario, seed, rules and dataset versions, and split.

Use the 20 `development` cases for prompt development and the 80 `evaluation` cases for held-out evaluation. Each scenario contributes two development and eight evaluation cases. Metadata and reference outputs are for the evaluation runner, not the model prompt. Running all 100 is possible, but mixing development and held-out cases must be reported explicitly.

The [evaluation runner](../../docs/evaluation.md) maps `input`, `expected_output`, and `metadata` to Langfuse dataset fields and preserves the local case ID in item metadata. It uploads only the cases selected for a live run, invokes OCI Responses, and compares the model's `selected_offer_id` with `expected_output.expected_offer_id`. A one-case development smoke test has verified this integration; the checked-in dataset remains the reproducible source for all 100 cases.

## Regeneration and verification

From the repository root:

```sh
conda activate agent-evals
python -m pip install -r requirements.txt
PYTHONPATH=src python -m agent_evals.generate_dataset
python -m pytest
```

The generator replaces its destination and companion manifest. Use `--output /tmp/express-order-check.json` to generate a review copy. The same catalogs, code, rules, and seed reproduce identical artifact bytes and manifest hashes. Do not change the seed or source catalogs for a published version without assigning a new dataset version.

See [the specification](../../specs/synthetic-dataset.md) for scope and acceptance criteria. No-winner and unresolved-tie inputs are tested against the oracle but excluded from these 100 cases.
