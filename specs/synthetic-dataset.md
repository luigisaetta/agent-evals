# Synthetic offer-selection dataset, version 1.0

## Scope and design

Implement a deterministic Python reference selector before implementing the generator. The reference selector validates task inputs and applies rules version 1.1 using exact decimal costs and calendar dates. It is a dataset oracle, not the LLM agent. No OCI or Langfuse calls are made in this change.

Generate 100 cases with exactly six offers each, using the existing catalogs. Use every requested part once, each destination ten times, and all suppliers across the dataset. Supplier identity is not a ranking factor; some cases include multiple offers from the same supplier.

Create ten cases for each scenario: all offers eligible with distinct costs; cheaper wrong part; cheaper wrong city; cheaper delivery on deadline; cheaper late delivery; two-way lowest-cost tie; three-way lowest-cost tie; cost taking precedence over earlier delivery; one-cent winning margin; and mixed filters leaving only one eligible offer.

Use a fixed seed (42), fixed date origin (2027-01-01), shuffled case/offer order, neutral offer IDs assigned before shuffling, and balanced winning positions (16 or 17 occurrences per position). Every case must have a unique best offer. Initial no-winner or unresolved-tie cases remain outside the generated dataset; the oracle raises explicit errors for those inputs.

## Artifacts and contract

* `src/agent_evals/selection.py`: input validation and deterministic selection, returning an offer ID.
* `src/agent_evals/generate_dataset.py`: command-line generator using only the standard library.
* `data/datasets/express-order-v1.json`: array of cases with `id`, `input`, `expected_output`, and `metadata`.
* `input`: only the request and six offers, following the existing task contract.
* `expected_output`: `{"expected_offer_id": "..."}`, separate from model input. A future Langfuse evaluator compares the agent's `selected_offer_id` with this reference.
* `metadata`: scenario, rules and dataset versions, generation seed, and split (`development` or `evaluation`). Reserve two cases per scenario for development (20 total) and eight for evaluation (80 total); do not tune on held-out cases.
* A companion manifest records catalog/rules hashes, seed, date origin, artifact hash, counts, and scenario/split/winner-position distribution. Hashes document source provenance without timestamps that would break reproducibility.

Prices are synthetic total offer costs derived from average catalog costs with an illustrative express-delivery surcharge. They are not supplier quotations. Dates are synthetic, independent of the execution date. All request and offer part/supplier/city references must exist in the catalogs.

## Acceptance criteria and verification

Use pytest for hand-authored oracle cases covering all eligibility filters, cost/date precedence, decimal precision, invalid input, duplicate IDs, no winner, unresolved ties, and order invariance. Validate the generated dataset against an independent eligibility/ranking calculation and scenario-specific assertions, plus counts, references, splits, position balance, and byte-for-byte reproducibility. Recheck stored reference outputs against the oracle. No network or model calls occur in tests.
