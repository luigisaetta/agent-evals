# Demo01: your first agent evaluation

Demo01 is the introductory exercise in this repository. Use it to configure the
environment, verify OCI model access, run your first repeatable evaluations and
learn how Langfuse connects inputs, generations and scores. A small, explicit
task makes integration problems easier to distinguish from model mistakes.

## What the demo evaluates

An Automotive Express Order supplies a structured JSON delivery request and six
structured supplier offers. One LLM call selects an offer using the
[selection rules](https://github.com/luigisaetta/agent-evals/blob/main/rules/offer-selection.md):

1. Match the requested part ID and plant city.
2. Deliver strictly before the request's exclusive deadline.
3. Minimize the total delivery cost in euros.
4. Break a price tie by choosing the earliest delivery.

Each offer includes its supplier ID. The final answer is
`{"selected_offer_id": "..."}`. The model makes the selection; Python validates
the answer and compares it with the dataset reference. The deterministic
reference selector is used when authoring data, not to answer for the model.

The dataset contains **100 cases**, each with six offers: **20 development**
cases and **80 evaluation** cases. Ten scenarios cover ineligible low prices,
deadline boundaries, price ties and other selection constraints. Cases have a
unique winner. Stock monitoring, supplier invitations and purchasing are outside
the evaluated task.

## 1. Prepare the environment

Run from the repository root. Create the Conda environment if needed:

```sh
conda create -n agent-evals python=3.11
conda activate agent-evals
python -m pip install -r requirements.txt
```

Create the root `.env` using
[.env.example](https://github.com/luigisaetta/agent-evals/blob/main/.env.example).
Set `OCI_REGION`, `OCI_MODEL`, `OCI_PROJECT_ID`, `LANGFUSE_BASE_URL`,
`LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`. OCI authentication uses your
signing key through `~/.oci/config`, profile `DEFAULT`, with optional
`OCI_CONFIG_FILE` and `OCI_PROFILE` overrides. A provider API key is not used.

The default interface is Responses. Set `OCI_MODEL_INTERFACE=langchain_oci` and
`OCI_COMPARTMENT_ID` for registered native chat models such as Cohere Command A;
see [shared configuration and compatibility](../docs/evaluation.md#setup).
The model and IAM permissions must support the selected OCI interface.
Configuration is shared with other demos: changing `OCI_MODEL`
affects subsequent runs of both Demo01 and Demo02. Do not commit `.env` or keys.

## 2. Verify the setup offline

```sh
./demo01/run_experiment.sh "Demo01 validation" --dry-run --split all
python -m pytest -q
```

Dry-run validation checks dataset structure and provenance without credentials,
model calls or Langfuse uploads. Unit tests use mocked external services. Neither
check measures the real model's task accuracy or verifies service connectivity.

## 3. Try one development case

```sh
./demo01/run_experiment.sh "Demo01 development smoke" \
  --split development --limit 1
```

This makes a real OCI Responses call and publishes the selected synthetic case,
experiment, generation and scores to Langfuse. To test OCI and local result
storage first without publishing, add `--no-langfuse`; the model is still called.

The launcher automatically selects the `agent-evals` environment, resolves the
repository paths, and prints the project banner and numbered startup activities.
An experiment name is required. The summary provides the experiment URL when
Langfuse is enabled.

## 4. Run an evaluation

```sh
# Default: 80 evaluation cases, one model call per case.
./demo01/run_experiment.sh "Demo01 baseline" --sleep-seconds 3

# Explicitly combine all 100 development and evaluation cases.
./demo01/run_experiment.sh "Demo01 all cases" --split all
```

The pause defaults to `EVAL_SLEEP_SECONDS` (two seconds if unset); the CLI option
overrides it. Calls are sequential, and automatic provider retries are disabled.
Other shared options include `--limit`, `--dataset`, `--rules`, `--env-file`,
`--output-dir` and `--compact-progress`.

The equivalent Python entry point is:

```sh
PYTHONPATH=src:. python -m demo01.evaluate --experiment-name "Demo01 baseline"
```

## What to inspect

Local files are written under ignored `data/runs/<run-id>/`:

| File | What it tells you |
| --- | --- |
| `metadata.json` | Model, experiment, settings and source provenance |
| `results.jsonl` | Per-case output/reference, model metadata, score, status and usage |
| `summary.json` | Counts, accuracy, overall success, KO cases and publication status |

In Langfuse, inspect the dataset item, its experiment result and the generation's
instructions, inputs, raw answer, configured model and token usage. Scores
include `selection_correct` for valid selections, `valid_output`, categorical
`execution_status` and `case_success` for every attempt.

Accuracy excludes unscored failures. Overall success includes all attempts in
its denominator; always inspect both rates and failure counts. A valid but wrong
selection is scored zero. Invalid JSON, incomplete output, API failures and
evaluator failures remain distinct from wrong selections. Publication status
`submitted_unverified` reports SDK submission, not an independent read-back check.

## Why this is a starting demo, and its limitations

Demo01 is intentionally small. For a model that already handles short structured
comparisons reliably, scores can reach the benchmark ceiling. A perfect run is
useful evidence that this configuration solves these cases; it provides little
separation between models that all solve them. It does not establish general
agent reliability or superiority on harder tasks.

The main limitations are:

* **The request is already structured.** There is no natural-language extraction,
  date interpretation, ambiguity resolution or conflicting email context.
* **The context and decision space are small.** Six offers and explicit rules do
  not exercise large catalogs, long context or evolving business policies.
* **Execution is one model call.** No planning, tool use, retrieval, memory,
  recovery loop or interaction with another agent is evaluated.
* **The data is synthetic and bounded.** A hundred designed examples do not
  establish production coverage. No-eligible-offer cases, unresolved ties,
  adversarial inputs and broader input-quality issues need additional policies
  and test cases.
* **The decision is deterministic.** For this exact structured problem, ordinary
  filtering and sorting can implement the business rules directly. The demo
  illustrates evaluating a model-backed component; it does not show that an LLM
  is necessary for offer ranking.
* **A run is a sample of behavior.** Exact-match correctness and recorded latency
  and usage do not measure every quality dimension or guarantee repeatability.
  Model, prompt and dataset changes require recorded, comparable experiments.

With capable models, use Demo01 primarily to establish the integration and
evaluation workflow. To explore harder agent behavior, move to
[Demo02](https://github.com/luigisaetta/agent-evals/blob/main/demo02/README.md),
which adds natural-language requests, extraction, date reasoning and a two-step
LangGraph pipeline. Its intermediate extraction score can expose errors hidden
by a correct final offer. The two demos share underlying business cases, so
their datasets are not independent benchmarks.

## Folder layout and compatibility

`evaluation.py` contains the concrete adapter and selection helpers;
`evaluate.py` and `run_experiment.sh` are the dedicated entry points. The common
runner, OCI transport, Langfuse integration, reference selector and dataset
authoring utilities remain in `src/agent_evals`, used by both demos. Catalogs,
rules and versioned datasets remain at their existing paths.

The root `run_experiment.sh` forwards legacy commands to this demo. The module
`agent_evals.tasks.offer_selection` re-exports the same objects from
`demo01.evaluation`, preserving Demo02 imports and existing user scripts. The
shared CLI remains available for other tasks with `--task`.

The refactor changes source locations and provenance hashes, not selection
prompts, rules, scores, namespaces, model settings or Demo02 behavior. Demo02's
source and prompts are untouched; its indirect import dependency is covered by
offline regression tests. New live experiments are optional integration checks,
not automatically performed as part of this folder move.
