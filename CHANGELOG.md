# Changelog

## Unreleased

* 2026-11-08: Add the deterministic offer-selection oracle, reproducible 100-case dataset with six offers per case across ten scenarios, development/evaluation splits, provenance manifest, and automated correctness and coverage checks. OCI execution and Langfuse publication remain future work.
* 2026-11-08: Add synthetic JSON reference catalogs with 50 suppliers, 100 automotive parts and indicative average unit costs in euros, and 10 European capital plant locations including Rome; document provenance and catalog contracts.
* 2026-11-08: Add the Automotive Express Order business context, multi-plant stock-replenishment workflow, and evaluation boundary limited to offer selection; retain the current city-based destination contract and ranking rules.
* 2026-11-08: Require `supplier_id` on every offer, update the JSON example, and advance the rules to version 1.1 without changing ranking criteria.

* 2026-11-08: Document offer fields, strict delivery-deadline eligibility, lowest-cost selection in euros, and earliest-delivery tie-breaking; add the versioned natural-language rules and a worked JSON example.
* 2026-11-08: Define the spare-part offer-selection task, rule-file and JSON input contracts, exact-match success criterion, and outstanding business-rule decisions.
* 2026-11-08: Add project working rules adapted from `llm-fine-tuning-on-mac`, covering the `agent-evals` Conda environment, OCI Generative AI Responses API, agent evaluations, and Langfuse Cloud with a future self-hosted option on OCI.
