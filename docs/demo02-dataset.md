# Demo02: natural-language requests, unchanged JSON offers

## Purpose and record shape

Demo02 keeps the same agent objective: receive a delivery request and select the best of six offers. Only the request representation changes:

| Field | Original demo | Demo02 |
| --- | --- | --- |
| `input.request` | JSON object with part, city and deadline | English string stating the same delivery requirement |
| `input.offers` | Six structured JSON offers | The exact same six JSON objects, in the same order |
| `expected_output` | Expected offer ID | Unchanged |

The input remains an object containing `request` and `offers`. It is not a single prose paragraph, and offers are not converted to text.

A request can read:

> We need the best offer for delivery of part PART-052 to our plant in Vienna strictly before 6 August 2027.

It asks for the best offer, or an offer/quotation, for delivery of a part to a plant before a date. It does not describe candidates, quote prices, identify suppliers, or add ranking criteria. The agent applies the business rules to the separate structured offers.

## Files

* [Demo02 dataset](https://github.com/luigisaetta/agent-evals/blob/main/data/datasets/demo02-express-order-v1.json)
* [Demo02 manifest](https://github.com/luigisaetta/agent-evals/blob/main/data/datasets/demo02-express-order-v1.manifest.json)
* [Request transformation script](https://github.com/luigisaetta/agent-evals/blob/main/src/agent_evals/generate_demo02_dataset.py)
* [Original structured dataset](https://github.com/luigisaetta/agent-evals/blob/main/data/datasets/express-order-v1.json)

## Preserved facts and outputs

All 100 cases preserve their original case IDs, case order, requested part, destination and deadline. Plant destinations continue to be represented by city names, as in the original request schema.

Every offer retains its `offer_id`, `supplier_id`, `part_id`, `delivery_location`, `delivery_date`, and `total_cost_eur`. No offer is rewritten, corrected, filtered or reordered. This includes offers that fail part, destination or deadline constraints.

The model's required answer remains a JSON object with `selected_offer_id`. The dataset keeps exactly the same `expected_output` object containing `expected_offer_id`. Scenario metadata and the 20-development/80-evaluation split are preserved.

## Request variety

There are ten English templates asking for an offer, the best offer, or a quotation, each used ten times. They vary sentence structure and the ordering of part, plant and date. Only request dates vary their written format: for example, `2027-08-06`, `6 August 2027`, or `August 6, 2027`. Dates inside the offer JSON are unchanged.

Requests preserve the original exclusive deadline, using wording such as "strictly before" or "earlier than". This avoids changing eligibility or the expected answer. Template choice, date style and transformation seed are recorded only in metadata.

## Regeneration and verification

From the repository root in the `agent-evals` Conda environment:

```sh
PYTHONPATH=src python -m agent_evals.generate_demo02_dataset
python -m pytest -q
```

The default seed is 42. Use `--seed` for another request-wording assignment, or `--output /tmp/demo02-review.json` for a separate review copy. The script validates the source manifest and refuses to overwrite the source dataset, its manifest, or its rule file.

Tests compare every offer array and reference output directly with the source. They also independently recover the part, city and date from each natural-language request, rebuild the original structured input in the test, and verify its expected winner. Other checks cover variety, metadata, source preservation and byte-for-byte reproducibility.

## Scope and next step

The dataset transformation makes no OCI calls or Langfuse uploads. A [two-step LangGraph agent](https://github.com/luigisaetta/agent-evals/blob/main/demo02/README.md) now accepts these inputs, extracts a structured request with one Responses call, and reuses Demo01's offer-selection code for a second Responses call. Use `python -m demo02.run_agent` as documented in that guide.

The Demo01 default adapter still expects a structured request. Demo02 now has its own evaluation adapter and launcher: `./demo02/run_experiment.sh "Demo02 baseline" --split all` evaluates every record of the default dataset (version 2, 300 records) and publishes to Langfuse; pass `--dataset` to select version 1. See the [Demo02 guide](https://github.com/luigisaetta/agent-evals/blob/main/demo02/README.md) for compact progress, per-node generation traces and result metadata, and the [task adaptation guide](https://github.com/luigisaetta/agent-evals/blob/main/docs/adapting-tasks.md) for future demos.

These datasets express the same underlying business cases in two request formats. They support paired comparisons; they are not independent benchmark sets. Preserve the development/evaluation boundary across both representations.

## Version 2: graded extraction difficulty

In version 1, three regular expressions recover every request exactly, so the extraction step cannot separate models. [demo02-express-order-v2.json](https://github.com/luigisaetta/agent-evals/blob/main/data/datasets/demo02-express-order-v2.json) derives three paired records from each source case, with IDs such as `EO-054-L0`, `EO-054-L1` and `EO-054-L2`. The [specification](https://github.com/luigisaetta/agent-evals/blob/main/specs/demo02-extraction-difficulty.md) defines the phrasing semantics and acceptance criteria.

| Level | Request form | Deadline wording | Distractors |
| --- | --- | --- | --- |
| L0 | The v1 sentence | Exclusive | None |
| L1 | One or two sentences, non-canonical part number | Inclusive ("no later than D" means exclusive D + 1) or "N calendar days after A" | A discontinued part, written before the requested part |
| L2 | Short email | Always arithmetic: "W weeks and N days after A", "N business days after A", "N days before a production restart on E", or "the original deadline X moved K days earlier/later" | The sender's office or a closed plant, the email date (unless the deadline counts from it), a previous delivery date, and in half the cases a discontinued part |

An L1 example, with reference `PART-052`, `Vienna`, `2027-08-06`:

> PART-083 has been discontinued. Please send your best offer for its replacement, part number 052, delivered to our Vienna plant at the latest on 2027-08-05.

Offers and `expected_offer_id` are identical across levels, so results per level isolate the effect of the request wording. `expected_output.expected_request` holds the source structured request for scoring the extraction step separately. `metadata.request_facts` records the stated deadline or anchor and offset, the part form, and the distractors; tests recompute the exclusive deadline from these facts without using generator code. When an offer carries another part or city, that trap value is used as the distractor.

An L2 example, with reference deadline `2027-08-19`: 19 business days after Thursday 22 July 2027 end on Wednesday 18 August, so the exclusive deadline is the following day.

> The delivery must arrive no later than 19 business days after the date of this request (22 July 2027); business days are Monday to Friday.

In 43 of the 100 L1 records and 43 of the 100 L2 records, a one-day deadline error changes the selected offer; in the other cases such an error is visible only in the extraction comparison.

A naive regex extractor (first `PART-NNN`, first city, first date) is exact on all 100 L0 records and on none of the L1 or L2 records. Text is composed from fixed fragments, without a language model, so references are correct by construction.

The levels were made harder on 2026-11-09, keeping version 2.0: a first L2 based on calendar days only was nearly saturated by `openai.gpt-oss-20b` (237/240 exact extractions). That earlier content is kept with its run's local results; see the revision history in the [specification](https://github.com/luigisaetta/agent-evals/blob/main/specs/demo02-extraction-difficulty.md#revision-history).

Regenerate from the repository root:

```sh
PYTHONPATH=src python -m agent_evals.generate_demo02_v2_dataset
python -m pytest -q tests/test_demo02_v2_dataset.py
```

The extraction prompt was updated to return the exclusive deadline for inclusive and relative wording and to normalize part numbers. Version 2 is the default dataset of the Demo02 agent CLI and evaluation adapter. Measuring extraction accuracy per level on a live model has not been done yet.
