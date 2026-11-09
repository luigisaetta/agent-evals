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

## Case success, additional scores and trace IDs

Added 2026-11-09. The correctness metric is published only for valid outputs, so its Langfuse average excludes invalid outputs and API or agent failures. A reviewer could not find every KO case from a single score, and errors in intermediate steps (for example a wrong extraction followed by a correct final choice) were not published at all.

* Every attempted case receives `case_success`: 1 when the status is `correct`, 0 for every other status, including `api_error`. Its average equals `success_rate_all_attempts`, and filtering `case_success = 0` lists exactly the KO cases.
* A task may supply an optional `extra_scores(case, result)` callback returning a dictionary of binary metrics. A value of `None` means not applicable (for example, the step was not reached because of an API error). Names must not collide with `valid_output`, `execution_status`, `case_success` or the task metric; values must be 0, 1 or `None`. Extra scores never change the case status. If the callback fails or returns an invalid value, the result records `extra_score_error` with the exception type and publishes no extra scores for that case.
* Each result stores `case_success`, `extra_scores` and, when tracking is enabled, the Langfuse `trace_id` (from `Langfuse.get_current_trace_id()` inside the experiment task, verified on SDK 5.2.0 on 2026-11-09). Trace IDs allow later scores to be attached to existing traces without rerunning.
* The summary adds `extra_score_summary`: for each extra metric, the number of scored cases, the number of 1 values and their ratio. The compact completion output prints one line per extra metric.
* The Langfuse evaluator publishes `case_success` and every non-null extra score with the existing scores. Run verification requires `case_success` on every item.
* Existing run files are not rewritten. Run-level Langfuse scores (`run_evaluators`) are out of scope.

Verified offline on 2026-11-09: 114 tests pass, covering `case_success` per status, extra-score storage, aggregation and publication, invalid or failing callbacks, reserved names, trace-ID capture with a mocked client, and Demo02 `extraction_correct` (including a wrong extraction behind a correct answer). Publication to Langfuse Cloud with these scores has not yet been run live.

## Verification and acceptance criteria

The optional multi-step invoker factory, additional source artifacts, per-result
model metadata and compact OK/KO progress are specified in
[the Demo02 evaluation specification](https://github.com/luigisaetta/agent-evals/blob/main/demo02/evaluation-spec.md).
Single-call adapters retain their existing defaults and file locations.

* Existing Express Order labels, generator artifacts, OCI signing and sleep defaults, failure categories, scoring and Langfuse score names remain correct. CLI arguments continue working.
* Run the Express Order dry run on all 100 cases. All domain rules and fields are confined to its adapter and existing generation/oracle code.
* Add a different small task in test fixtures, with text/classification inputs and outputs, a different metric, and a different rule-source key. Exercise the same dataset loader, engine, CLI module selection, provider request and mocked Langfuse path without altering core code.
* Cover invalid custom output, valid wrong answers, scorer failure, input/reference isolation, task/version metadata, namespaces, and errors importing a task module.
* Run the automated suite; no live provider or Langfuse calls are needed. Document adaptation steps and result-schema migration.
