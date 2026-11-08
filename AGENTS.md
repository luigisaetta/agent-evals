# AGENTS.md

This repository contains a practical Python project for experimenting with evaluations of an agent that performs a well-defined task. It uses models hosted on OCI Generative AI through the Responses API and Langfuse for tracing, datasets, experiments, and evaluation results.

## Repository purpose

The business use case is Automotive Express Order. The company manufactures cars at multiple plants. Reduced stock availability for a part triggers an Express Order, and multiple suppliers are invited to submit offers. This repository evaluates only the agent's selection of the best received offer for the requesting plant. Stock monitoring, order initiation, supplier invitations, offer collection, and purchase-order placement are outside the current scope.

Keep the repository focused on a clear, reproducible workflow from agent implementation to dataset preparation, evaluation, and publication of experiment results in Langfuse.

The immediate objectives are:

1. Build the agent behaviour to be evaluated, with an explicit task and success criteria.
2. Build the evaluation workflow, including datasets, evaluators, and repeatable experiments.
3. Publish the relevant traces, datasets, scores, and experiment results to Langfuse.

Use Langfuse Cloud initially. Keep connection settings configurable so a future self-hosted Langfuse instance on OCI can be adopted without rewriting agent or evaluation logic. Deploying that instance is outside the immediate scope.

Avoid unrelated AI demonstrations, model training, infrastructure deployment, or large frameworks unless explicitly required by a specification.

## Spec-driven workflow

Work spec-first for every feature or meaningful change:

1. Read the relevant specification in `specs/` before implementation.
2. Create or update a concise specification when the requested behaviour is not covered.
3. State the problem, scope, assumptions, acceptance criteria, and verification approach before writing code.
4. Implement only what the specification requires, then update the specification if an agreed behaviour changes.
5. Record important implementation decisions in the specification or its linked documentation.

Specifications are source-controlled project artifacts, not disposable planning notes. Keep them concise, testable, and in English.

## Language and documentation

* All project documentation, source-code comments, Markdown files, notebook narrative cells, and application output must be written in English. Conversation with the user may remain in the user's language.
* Keep documentation practical, accurate, and aligned with the implementation.
* Maintain `CHANGELOG.md` in the repository root. Record every user-visible addition and every significant change under `Unreleased` before it is released, prefixing each new entry with its ISO 8601 calendar date (`YYYY-MM-DD`).
* Make the agent task, exact model identifier, dataset provenance and version, prompt version, evaluator configuration, and expected outputs explicit.
* Do not claim OCI model availability, Responses API compatibility, SDK capabilities, Langfuse features, or evaluation quality unless verified by implementation or authoritative documentation.
* Do not commit private datasets, personal data, credentials, generated traces, experiment outputs, or caches.

## Codex working rules

When working in this repository, Codex should:

* Inspect the existing project structure and applicable specifications before editing.
* Prefer small, coherent changes over broad rewrites.
* Preserve user changes already present in the working tree.
* Do not create commits unless explicitly asked.
* Do not add dependencies without a clear agent, evaluation, observability, or notebook need.
* Do not run destructive commands or discard existing changes unless explicitly requested.
* Never hard-code credentials, private URLs, local machine paths, or personally identifiable data.
* Use environment variables, the supported OCI credential mechanism, and ignored `.env` files for secrets; document variable names and safe placeholders.
* Make model calls, network downloads, and uploads explicit. Upload only the data required by the specified workflow and avoid silently publishing local or sensitive data.
* When uncertain, document the assumption, leave a clear TODO, or ask for clarification.

## Python environment

Use the `agent-evals` Conda environment for development, notebooks, and checks. Activate it before running project commands, or use `conda run -n agent-evals ...`. Do not rely on globally installed packages or another Conda environment.

Install Python packages from `requirements.txt`. Keep dependencies compatible with the selected Python version, OCI Responses API client, and Langfuse SDK, and document any required version constraints.

## Python and notebook conventions

Every Python source file must start with this multiline header, using the actual modification date:

```python
"""
Author: L. Saetta
Date last modified: YYYY-MM-DD
License: MIT
Description: Brief description of the responsibilities and functions contained in this file.
"""
```

Use accurate Google-style docstrings for modules, classes, and public functions. Keep notebooks focused on one learning goal, restartable from a clean kernel, and backed by reusable code in `src/` when logic grows beyond a short demonstration.

## Agent design expectations

* Define the agent's task, input/output contract, allowed tools, stopping conditions, and success criteria before implementation.
* Access OCI Generative AI models through the Responses API. Verify the selected model, endpoint, authentication mechanism, and supported request parameters rather than assuming compatibility with another provider.
* Separate configuration, model access, agent logic, tool execution, evaluation, and Langfuse integration where practical.
* Keep model identifiers, endpoints, region, generation parameters, timeouts, retry policy, and execution limits visible in configuration. Never log credentials.
* Preserve structured outputs and relevant execution metadata so evaluators can assess both final answers and task execution where required.
* Clearly report authentication, configuration, model, tool, and output-validation failures instead of silently changing models or behaviour.

## Evaluation design expectations

* Start with a small, representative dataset for the defined task, including normal cases, edge cases, and expected failures.
* Validate dataset schema, stable case identifiers, required inputs, references or assertions, duplicates, and provenance with actionable errors.
* Keep development cases separate from held-out evaluation cases when tuning agent behaviour or prompts. Do not use held-out results to repeatedly tune the agent without documenting that reuse.
* Define each metric, rubric, score range, and pass threshold explicitly. Prefer deterministic checks when the task permits them; use model-based judges only with a documented rubric and configuration.
* Record dataset version, agent and prompt version, model identifiers, generation parameters, evaluator version, and run identifier for every experiment. Record seeds where supported without implying fully deterministic model output.
* Distinguish agent errors, evaluator errors, and infrastructure failures from valid evaluation scores. Report failures and sample counts alongside aggregate results.
* Make concurrency, sample limits, repeat counts, and retry limits configurable so evaluation cost and runtime remain controlled.
* Preserve per-case results and enough metadata to compare experiments and investigate regressions.

## Langfuse integration

* Use Langfuse Cloud as the initial destination and configure its host and credentials externally.
* Keep agent execution usable without Langfuse when tracing is disabled. An explicit publication command must report upload failures and must not claim success when results were not published.
* Link evaluation cases, agent traces, scores, and experiment metadata using the capabilities supported by the selected Langfuse SDK version.
* Use stable case and run identifiers to avoid accidental duplicate dataset entries or results when retrying publication.
* Exclude credentials and redact sensitive inputs, outputs, tool arguments, and metadata before sending them to Langfuse or an external model.
* Keep environment-specific settings outside agent and evaluator logic to support a future move to self-hosted Langfuse on OCI.

## Testing and verification

New behaviour needs proportionate automated tests with `pytest`. Unit tests must not call real models, contact OCI or Langfuse, or download datasets; mock external clients or use tiny local fixtures. Real model calls and Langfuse publication should be optional, explicitly enabled integration checks.

Test dataset validation, agent input/output contracts, evaluator scoring, error handling, and publication mapping where relevant. Separate software correctness tests from experiments measuring agent quality.

Run relevant formatting, linting, and tests before considering work complete. If a check cannot run because of missing credentials, service access, datasets, or dependencies, state it clearly.

## Definition of done

A change is done only when:

* Its scope and acceptance criteria are captured in a specification.
* Documentation and setup instructions reflect the changed behaviour.
* Agent task, dataset, model, evaluator, and configuration assumptions are explicit.
* Relevant checks have been run or their limitation has been documented.
* For changes involving publication, Langfuse results are verifiable or the missing integration check is explicitly documented.
* No credentials, private data, generated experiment artifacts, or caches have been added to version control.
