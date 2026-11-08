# Changelog

## Unreleased

* 2026-11-08: Surface safe root-cause categories for OCI connection failures in evaluation results and progress messages, including DNS resolution failures hidden by APIConnectionError.
* 2026-11-08: Require an explicit experiment name, use it in Langfuse with distinct per-execution run names, and add the executable root-level run_experiment.sh launcher for the agent-evals Conda environment.
* 2026-11-08: Rewrite the main README for a public demo audience, covering objectives, Automotive Express Order context, evaluation scenarios and metrics, architecture, OCI/Langfuse tooling, quick start, and verified integration scope.
* 2026-11-08: Add a tqdm progress bar to local and Langfuse evaluation runs, preserving per-case status messages and counting failed attempts.
* 2026-11-08: Verify the OCI IAM Responses and Langfuse integration on one development case after environment correction; confirm the correct selection and remotely persisted evaluation scores.
* 2026-11-08: Add the sequential OCI Responses evaluation runner with user-principal signing from the OCI config file, dotenv settings, configurable inter-call sleep, local result persistence, and Langfuse dataset/experiment tracking; add mocked integration tests and setup documentation.
* 2026-11-08: Add the deterministic offer-selection oracle, reproducible 100-case dataset with six offers per case across ten scenarios, development/evaluation splits, provenance manifest, and automated correctness and coverage checks. OCI execution and Langfuse publication remain future work.
* 2026-11-08: Add synthetic JSON reference catalogs with 50 suppliers, 100 automotive parts and indicative average unit costs in euros, and 10 European capital plant locations including Rome; document provenance and catalog contracts.
* 2026-11-08: Add the Automotive Express Order business context, multi-plant stock-replenishment workflow, and evaluation boundary limited to offer selection; retain the current city-based destination contract and ranking rules.
* 2026-11-08: Require `supplier_id` on every offer, update the JSON example, and advance the rules to version 1.1 without changing ranking criteria.

* 2026-11-08: Document offer fields, strict delivery-deadline eligibility, lowest-cost selection in euros, and earliest-delivery tie-breaking; add the versioned natural-language rules and a worked JSON example.
* 2026-11-08: Define the spare-part offer-selection task, rule-file and JSON input contracts, exact-match success criterion, and outstanding business-rule decisions.
* 2026-11-08: Add project working rules adapted from `llm-fine-tuning-on-mac`, covering the `agent-evals` Conda environment, OCI Generative AI Responses API, agent evaluations, and Langfuse Cloud with a future self-hosted option on OCI.
