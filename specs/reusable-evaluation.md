# Reusable evaluation runner

## Objective and scope

Separate the Express Order task from reusable dataset loading, OCI inference, sequential execution, result persistence, diagnostics, and Langfuse tracking. Keep the design readable: one small task descriptor and a Python module per use case, without a plugin framework, inheritance hierarchy, or new dependencies.

## Task boundary

An `EvaluationTask` descriptor supplies task name/title, relative default dataset/rules paths, the manifest's rule-source key, Langfuse dataset namespace and metric name, task version, and four callables:

1. `validate_case(case)`: validate domain input and expected output without recomputing labels.
2. `build_instructions(rules)`: construct the task prompt and output contract.
3. `parse_output(raw_output, input)`: parse and validate the model answer, returning a JSON-compatible object.
4. `score_output(output, expected_output)`: assign binary correctness (0 or 1).

The Express Order adapter is `agent_evals.tasks.offer_selection` and exports `TASK`. It owns all offer fields, the six-offer requirement, response-ID membership, exact-match scoring, business title, prompt and selection metric name. Existing generator/reference-selector modules remain specific dataset-authoring tools and do not move or change their generated artifacts.

## Shared runner

* `--task` selects an importable module exporting `TASK`; the default adapter preserves existing shell and CLI commands. Loading a task module executes local Python code and is intended for trusted project modules.
* Generic dataset loading checks case envelopes (`id`, `input`, `expected_output`, `metadata`), unique IDs, split and version consistency, and dataset/rule hashes, then delegates domain validation. No expected-winner recomputation is introduced.
* The OCI client accepts final instructions and JSON-serializable input. It contains no business prompt or output fields.
* Generic execution delegates parsing/scoring, stores structured `output` and `expected_output`, and preserves pacing, raw output, usage, error safety, progress, and initialization logs. Distinguish evaluator implementation failures from invalid model output and API failures.
* Result schema version 2 replaces flat `selected_offer_id`/`expected_offer_id` with generic nested fields, and replaces `selection_accuracy` with `accuracy`. Existing run files remain unchanged. Include task identity/version and metric name in new run metadata and summaries.
* Langfuse setup takes task-supplied namespace/title and manifest versions. A generic evaluator publishes the task's already-computed score under its metric name, plus existing validity/status scores. It never knows offer identifiers.
* Banner title, progress text and dry-run output must work for another domain. Record hashes for task callbacks as well as shared code so custom modules are reproducible.
* Initial reuse targets binary-correctness tasks with local JSON datasets and natural-language rule files. Multi-metric/fractional scoring, alternative providers, and generalized synthetic generation are outside this refactor.

## Verification and acceptance criteria

* Existing Express Order labels, generator artifacts, OCI signing and sleep defaults, failure categories, scoring and Langfuse score names remain correct. CLI arguments continue working.
* Run the Express Order dry run on all 100 cases. All domain rules and fields are confined to its adapter and existing generation/oracle code.
* Add a different small task in test fixtures, with text/classification inputs and outputs, a different metric, and a different rule-source key. Exercise the same dataset loader, engine, CLI module selection, provider request and mocked Langfuse path without altering core code.
* Cover invalid custom output, valid wrong answers, scorer failure, input/reference isolation, task/version metadata, namespaces, and errors importing a task module.
* Run the automated suite; no live provider or Langfuse calls are needed. Document adaptation steps and result-schema migration.
