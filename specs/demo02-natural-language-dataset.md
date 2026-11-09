# Demo02: natural-language requests with structured offers

## Objective and scope

Derive a second dataset from the existing 100 Express Order cases. Change only `input.request` from a structured object to a varied English string specifying delivery of the requested part to the plant in the requested city before the deadline. Keep `input` as an object containing `request` and `offers`. Keep `input.offers` exactly equal to the source array, including all six JSON offer objects and their order.

The request asks for the best offer, or an offer/quotation, for delivery of a part to a plant before the stated deadline. Vary this wording while retaining the same three business facts. Do not describe individual candidates, mention supplier IDs, quote prices, add ranking criteria, or identify the expected answer. The agent's task remains selecting the best of the six structured offers, and the output contract remains unchanged.

This is data preparation only. Do not modify the original dataset, add a runner adapter, invoke a model, or publish to Langfuse.

## Artifacts and representation

* `src/agent_evals/generate_demo02_dataset.py`: reproducible request-only transformation using seed 42.
* `data/datasets/demo02-express-order-v1.json`: 100 case records with a string in `input.request` and the original JSON array in `input.offers`.
* `data/datasets/demo02-express-order-v1.manifest.json`: source lineage, rules and transformer hashes, output hash, versions, seed, and scenario/split/request-template/date-style counts.
* `docs/demo02-dataset.md`: review, regeneration and integration notes.

Use ten request phrasings, each appearing ten times, and vary unambiguous English date formats. Preserve the original requested part ID, city and exclusive deadline. The source schema represents a plant by its delivery city; do not introduce new plant identifiers or change delivery eligibility. Keep every offer field and `expected_output` unchanged. Preserve case IDs, case order, metadata scenarios and development/evaluation splits, adding only transformation metadata.

## Verification

* Confirm 100 paired cases, six unchanged structured offers per case, unchanged references, IDs, ordering, scenarios and splits.
* Independently extract the three requested facts from every English string and compare them with the source request. Combine that recovered request with the unchanged offers, then verify the original winner with the deterministic selector in tests.
* Verify that each request asks for an offer or quotation and contains no candidate/supplier identifiers, prices, additional ranking rules or expected-answer fields.
* Verify template/date variety, reproducible dataset/manifest bytes, source hashes, source preservation and source-overwrite protection.
* Document that the default adapter expects a structured request and a Demo02 adapter is still required for live evaluation. These are paired representations of the same cases, not independent benchmark data.
