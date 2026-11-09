# Demo01 folder and introductory guide

## Objective and scope

Give the first demonstration the same dedicated-folder layout as subsequent
demos. Position Demo01 as an environment setup and first evaluation exercise:
one OCI Responses call selects among six structured offers using explicit rules.
Explain its limited scope as a benchmark for capable language models.

## Layout and compatibility

* Move the concrete offer-selection adapter to `demo01/evaluation.py` and the
  actual shell launcher to `demo01/run_experiment.sh`; add the package and a thin
  `demo01/evaluate.py` wrapper selecting the adapter through the shared CLI.
* Keep a small root launcher forwarding to the new shell entry point, preserving
  existing commands and generic `--task` overrides. Preserve argument boundaries,
  exit codes, automatic Conda selection and execution from any working directory.
* Keep `agent_evals.tasks.offer_selection` as an explicit re-export module for
  existing imports, including Demo02 and both Demo02 dataset generators. Re-export
  the identical callback objects and TASK; do not duplicate implementations.
* Leave shared configuration, evaluation engine, transport, console, publication,
  generator and deterministic selector in `src/agent_evals`. Both demos depend on
  these authoring/runtime utilities. Leave catalogs, datasets, manifests and rules
  at their current paths and preserve their bytes and source hashes.
* Preserve prompts, validation, scoring, task identity/version, Langfuse namespace,
  metric names, model settings, pacing, extra scores and default split selection.
  Callback source paths and newly recorded source hashes may reflect the move.

## Documentation and Demo02 impact

Add an English README covering setup, IAM and `.env`, offline checks, a live
development smoke command, evaluation commands, Langfuse inspection, metrics,
scope and limitations. Explain that structured inputs, short explicit rules,
six candidates, synthetic data and a unique exact answer exercise a narrow task;
high scores cannot establish broad agent competence. Treat score saturation as
a limitation when a tested model already solves these examples, rather than
claiming all present-day models perform equally well. Contrast with Demo02's
request extraction and date interpretation.

Update current documentation and links to use the dedicated Demo01 entry point.
Document the compatibility shims and the indirect Demo02 dependency. Demo02's
Python files, prompts, task adapter, launcher and datasets do not require edits.
The import target's source location changes; its behavior must remain identical.

## Verification

Run the offline suite, including both demos' mocked execution/publication and
dataset provenance tests. Verify old imports alias the canonical Demo01 symbols,
the moved launcher resolves the repository from another working directory and
forwards quoted arguments/exit status, and both old/new shell launchers support
offline validation. Validate all 100 Demo01 and 300 default Demo02 records via
their launchers. Check shell syntax and diff whitespace. Do not run live OCI or
Langfuse experiments for this refactor; the user will choose further live checks
after reviewing the reported Demo02 impact.
